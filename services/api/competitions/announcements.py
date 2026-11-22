"""Results announcements (REQ-043, TASK-085): a draft drawn only from official results.

The generator lists every match of the chosen scope (a session, a round, a day, an event or the whole
tournament) with both sides in the order of the match card, the games won and each game's points, and
marks a walkover (W/O), a retirement (ret.) and a disqualification (DQ). A match without an official
result is listed as pending. It adds the group tables a group stage has and the podium of an event that
is complete. It never makes anything up: no commentary, no shots, no ratings, nothing private (names and
scores only). The organizers edit the draft before publishing; the text they publish is frozen.
"""

from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.exceptions import ApiException

from . import ceremony, drawing
from .models import (
    Announcement,
    DrawVersion,
    Event,
    Match,
    OfficialResult,
    Rubber,
    RubberPlayer,
    ScheduleSession,
    Tournament,
)
from .official import title

Scope = Announcement.Scope
MAX_BODY = 5000
MAX_TITLE = 120
OUTCOME_MARK = {
    Match.Outcome.WALKOVER: "W/O",
    Match.Outcome.RETIRED: "ret.",
    Match.Outcome.DISQUALIFIED: "DQ",
}
PLACE = {1: "Winner", 2: "Runner-up", 3: "Third place"}


def _finished(game) -> bool:
    a, b = game
    return max(a, b) >= 11 and abs(a - b) >= 2


def score_line(a: str, b: str, result: OfficialResult | None) -> str:
    """ "Amina 3-1 Brian (11-7, 9-11, 11-5, 11-8)", side a first as on the match card. A game a retirement
    or a disqualification left unfinished is shown but not counted as won."""
    if result is None:
        return f"{a} v {b}: pending"
    winner = a if result.winner_id == result.match.entry_a_id and result.rubber_id is None else None
    if result.rubber_id is not None:
        winner = None  # rubbers name their winning side below
    mark = OUTCOME_MARK.get(result.outcome)
    if result.outcome == Match.Outcome.WALKOVER:
        return f"{a} v {b}: W/O, {winner or _winner_name(result, a, b)} goes through"
    games = [list(game) for game in result.games]
    won_a = sum(1 for game in games if _finished(game) and game[0] > game[1])
    won_b = sum(1 for game in games if _finished(game) and game[1] > game[0])
    line = f"{a} {won_a}-{won_b} {b}"
    if games:
        line += " (" + ", ".join(f"{x}-{y}" for x, y in games) + ")"
    if mark:
        line += f" {mark}, {_winner_name(result, a, b)} wins"
    return line


def _winner_name(result: OfficialResult, a: str, b: str) -> str:
    entry_a = result.rubber.match.entry_a_id if result.rubber_id else result.match.entry_a_id
    return a if result.winner_id == entry_a else b


class Scoped:
    """What one announcement covers, checked against the tournament."""

    def __init__(
        self, tournament: Tournament, scope: str, *, event=None, stage="", round=None, day=None, session=None
    ):
        self.tournament = tournament
        self.scope = scope
        self.event = event
        self.stage = stage
        self.round = round
        self.day = day
        self.session = session
        self.zone = ZoneInfo(tournament.timezone)

    def heading(self) -> str:
        name = self.tournament.name
        if self.scope == Scope.EVENT:
            return f"{name}: {self.event.name} results"
        if self.scope == Scope.ROUND:
            return f"{name}: {self.event.name}, {self.round_name()} results"
        if self.scope == Scope.DAY:
            return f"{name}: results of {self.day.strftime('%A %-d %B')}"
        if self.scope == Scope.SESSION:
            label = self.session.name or f"session of {self.session.day.strftime('%A %-d %B')}"
            return f"{name}: {label} ({self.session.starts:%H:%M}-{self.session.ends:%H:%M}) results"
        return f"{name}: results"

    def round_name(self) -> str:
        if self.stage == Match.Stage.GROUP:
            return f"group stage round {self.round}"
        draw = self.event.draws.filter(status=DrawVersion.Status.PUBLISHED).first()
        rounds = (
            draw.matches.filter(stage=Match.Stage.KNOCKOUT)
            .order_by("-round")
            .values_list("round", flat=True)
            .first()
            if draw
            else None
        )
        return drawing.round_name(self.round, rounds).lower() if rounds else f"round {self.round}"

    def matches(self) -> list[Match]:
        """The scope's matches with two sides, in programme order: events as listed, then stage, round,
        group and position."""
        found = (
            Match.objects.filter(
                draw__event__tournament=self.tournament,
                draw__status=DrawVersion.Status.PUBLISHED,
                entry_a__isnull=False,
                entry_b__isnull=False,
            )
            .exclude(status=Match.Status.BYE)
            .exclude(draw__event__status=Event.Status.CANCELLED)
            .select_related("draw__event", "entry_a", "entry_b")
            .prefetch_related("entry_a__players__user", "entry_b__players__user")
            .order_by(
                "draw__event__position", "draw__event__created_at", "stage", "round", "group", "position"
            )
        )
        if self.scope in (Scope.EVENT, Scope.ROUND):
            found = found.filter(draw__event=self.event)
        if self.scope == Scope.ROUND:
            found = found.filter(stage=self.stage, round=self.round)
        matches = list(found)
        if self.scope == Scope.DAY:
            decided = self._decided_on()
            matches = [m for m in matches if self._local_day(m.scheduled_at) == self.day or m.id in decided]
        if self.scope == Scope.SESSION:
            start = datetime.combine(self.session.day, self.session.starts, self.zone)
            end = datetime.combine(self.session.day, self.session.ends, self.zone)
            events = {event.id for event in self.session.events.all()}
            matches = [
                m
                for m in matches
                if m.scheduled_at
                and start <= m.scheduled_at < end
                and (not events or m.draw.event_id in events)
            ]
        return matches

    def _local_day(self, moment) -> date | None:
        return moment.astimezone(self.zone).date() if moment else None

    def _decided_on(self) -> set:
        start = datetime.combine(self.day, time.min, self.zone)
        end = datetime.combine(self.day, time.max, self.zone)
        return set(
            OfficialResult.objects.filter(
                match__draw__event__tournament=self.tournament,
                rubber__isnull=True,
                current=True,
                first_accepted_at__range=(start, end),
            ).values_list("match_id", flat=True)
        )


def generate(scoped: Scoped) -> tuple[str, str, list[Match]]:
    """(title, text, matches covered) for the scope, from the official results as they stand."""
    matches = scoped.matches()
    ids = [match.id for match in matches]
    results = {
        result.match_id: result
        for result in OfficialResult.objects.filter(
            match_id__in=ids, rubber__isnull=True, current=True
        ).select_related("match")
    }
    rubbers = _rubbers(ids)
    by_event: dict = defaultdict(list)
    for match in matches:
        by_event[match.draw.event].append(match)

    lines = [scoped.heading(), ""]
    for event, played in by_event.items():
        lines.append(event.name)
        heading = None
        for match in played:
            here = _round_heading(match, event)
            if here != heading:
                heading = here
                lines.append(here)
            a, b = title(match.entry_a), title(match.entry_b)
            lines.append(score_line(a, b, results.get(match.id)))
            for rubber, result, names in rubbers.get(match.id, []):
                lines.append(f"  Rubber {rubber.position}: {score_line(names[0], names[1], result)}")
        lines.extend(_group_tables(event, played, scoped))
        if scoped.scope in (Scope.EVENT, Scope.TOURNAMENT):
            lines.extend(_podium(event))
        lines.append("")
    if not matches:
        lines.append("No matches in this selection yet.")
    text = "\n".join(lines).strip()
    return scoped.heading()[:MAX_TITLE], text[:MAX_BODY], matches


def _round_heading(match: Match, event: Event) -> str:
    if match.stage == Match.Stage.GROUP:
        return (
            f"{drawing.group_name(match.group)}, round {match.round}"
            if match.group
            else f"Round {match.round}"
        )
    rounds = _knockout_rounds(match.draw_id)
    return drawing.round_name(match.round, rounds)


def _knockout_rounds(draw_id) -> int:
    return (
        Match.objects.filter(draw_id=draw_id, stage=Match.Stage.KNOCKOUT)
        .order_by("-round")
        .values_list("round", flat=True)
        .first()
        or 1
    )


def _rubbers(match_ids: list) -> dict:
    """For each tie, its decided rubbers: (rubber, current result, (side a's names, side b's names))."""
    found: dict = defaultdict(list)
    results = {
        result.rubber_id: result
        for result in OfficialResult.objects.filter(
            match_id__in=match_ids, rubber__isnull=False, current=True
        ).select_related("rubber__match")
    }
    if not results:
        return found
    players: dict = defaultdict(lambda: ([], []))
    for place in RubberPlayer.objects.filter(rubber_id__in=results).select_related("user"):
        players[place.rubber_id][0 if place.side == RubberPlayer.Side.A else 1].append(
            place.user.display_name
        )
    for rubber in Rubber.objects.filter(id__in=results).order_by("position"):
        a, b = players[rubber.id]
        found[rubber.match_id].append((rubber, results[rubber.id], (" / ".join(a), " / ".join(b))))
    return found


def _group_tables(event: Event, played: list[Match], scoped: Scoped) -> list[str]:
    """The tables of the groups this selection played in, as they stand; an unfinished one says so."""
    groups = sorted({match.group for match in played if match.stage == Match.Stage.GROUP and match.group})
    if not groups:
        return []
    draw = played[0].draw
    lines = []
    for group in groups:
        rows, complete = drawing.group_table(draw, group)
        names = {
            str(entry.id): title(entry) for entry in event.entries.filter(id__in=[row.member for row in rows])
        }
        standing = ", ".join(
            f"{row.rank}. {names.get(str(row.member), '')} ({row.won}-{row.lost})" for row in rows
        )
        lines.append(f"{drawing.group_name(group)} table{'' if complete else ' so far'}: {standing}")
    return lines


def _podium(event: Event) -> list[str]:
    """The podium of a completed event, joint places together."""
    places = ceremony.podium(event)
    if not places:
        return []
    from .models import Entry

    entries = {
        entry.id: title(entry)
        for entry in Entry.objects.filter(id__in=[e for _, ids in places for e in ids]).prefetch_related(
            "players__user"
        )
    }
    return [
        f"{PLACE.get(place, f'Place {place}')}: {' and '.join(entries.get(e, '') for e in ids)}"
        for place, ids in places
    ]


def scoped_from(tournament: Tournament, asked: dict) -> Scoped:
    """The scope the organizers asked for, every part of it checked against the tournament."""
    scope = asked["scope"]
    event = None
    if scope in (Scope.EVENT, Scope.ROUND):
        event = tournament.events.filter(pk=asked.get("event_id")).first()
        if event is None:
            raise ApiException("invalid_scope", "Choose one of this tournament's events.", 400)
    if scope == Scope.ROUND:
        if asked.get("stage") not in Match.Stage.values or not asked.get("round"):
            raise ApiException("invalid_scope", "Choose the stage and round.", 400)
        if not Match.objects.filter(
            draw__event=event,
            draw__status=DrawVersion.Status.PUBLISHED,
            stage=asked["stage"],
            round=asked["round"],
        ).exists():
            raise ApiException("invalid_scope", "That round isn't in the event's published draw.", 400)
    if scope == Scope.DAY and not asked.get("day"):
        raise ApiException("invalid_scope", "Choose the day.", 400)
    session = None
    if scope == Scope.SESSION:
        session = ScheduleSession.objects.filter(tournament=tournament, pk=asked.get("session_id")).first()
        if session is None:
            raise ApiException("invalid_scope", "Choose one of this tournament's sessions.", 400)
    return Scoped(
        tournament,
        scope,
        event=event,
        stage=asked.get("stage") or "",
        round=asked.get("round"),
        day=asked.get("day"),
        session=session,
    )


def draft(tournament: Tournament, scoped: Scoped, actor, amends: Announcement | None = None) -> Announcement:
    """A new draft with the generated text."""
    heading, text, matches = generate(scoped)
    made = Announcement.objects.create(
        tournament=tournament,
        scope=scoped.scope,
        event=scoped.event,
        stage=scoped.stage,
        round=scoped.round,
        day=scoped.day,
        session=scoped.session,
        title=heading if amends is None else f"Amended: {heading}"[:MAX_TITLE],
        body=text,
        created_by=actor,
        amends=amends,
    )
    made.covers.set(matches)
    return made


def scoped_of(announcement: Announcement) -> Scoped:
    return Scoped(
        announcement.tournament,
        announcement.scope,
        event=announcement.event,
        stage=announcement.stage,
        round=announcement.round,
        day=announcement.day,
        session=announcement.session,
    )


def outdate(match: Match) -> None:
    """A result of `match` changed: published announcements that covered it are now out of date. Called in
    the transaction that changes the result, so it is undone with it."""
    Announcement.objects.filter(
        covers=match, status=Announcement.Status.PUBLISHED, outdated_at__isnull=True
    ).update(outdated_at=timezone.now())


def ensure_draft(announcement: Announcement) -> None:
    if announcement.status != Announcement.Status.DRAFT:
        raise ApiException(
            "announcement_published",
            "A published announcement can't change. Publish an amendment instead.",
            409,
        )
