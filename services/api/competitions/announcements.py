"""Results announcements (REQ-043, TASK-085): a draft drawn only from official results.

The generator lists every match of the chosen scope (a session, a round, a day, an event or the whole
tournament) with both sides in the order of the match card, the games won (rubbers won for a team tie)
and each game's points, and marks a walkover (W/O), a retirement (ret.) and a disqualification (DQ). A
match without an official result is listed as pending, sides still to be decided included. It adds the
tables of the groups played and the podium of a completed event whose final is in the selection. It never
makes anything up: no commentary, no shots, no ratings, nothing private (names and scores only). The
organizers edit the draft before publishing; the text they publish is frozen.
"""

from collections import defaultdict
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.db.models import Max
from django.utils import timezone

from core.exceptions import ApiException

from . import ceremony, drawing
from .models import (
    Announcement,
    Award,
    DrawVersion,
    Entry,
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
TO_BE_DECIDED = "To be decided"


def _finished(game) -> bool:
    a, b = game
    return max(a, b) >= 11 and abs(a - b) >= 2


def score_line(a: str, b: str, result: OfficialResult | None, a_won: bool, rubbers=None) -> str:
    """ "Amina 3-1 Brian (11-7, 9-11, 11-5, 11-8)", side a first as on the match card. A game a retirement
    or a disqualification left unfinished is shown but not counted as won. A team tie counts `rubbers`
    (won by side a, by side b) instead of games."""
    if result is None:
        return f"{a} v {b}: pending"
    winner = a if a_won else b
    if result.outcome == Match.Outcome.WALKOVER:
        return f"{a} v {b}: W/O, {winner} goes through"
    games = [list(game) for game in result.games]
    if rubbers is not None:
        won_a, won_b = rubbers
    else:
        won_a = sum(1 for game in games if _finished(game) and game[0] > game[1])
        won_b = sum(1 for game in games if _finished(game) and game[1] > game[0])
    line = f"{a} {won_a}-{won_b} {b}"
    if games:
        line += " (" + ", ".join(f"{x}-{y}" for x, y in games) + ")"
    mark = OUTCOME_MARK.get(result.outcome)
    if mark:
        line += f" {mark}, {winner} wins"
    return line


class Selection:
    """What one announcement covers (its scope and what the scope names), checked against the tournament."""

    def __init__(
        self, tournament: Tournament, scope: str, *, event=None, stage="", number=None, day=None, session=None
    ):
        self.tournament = tournament
        self.scope = scope
        self.event = event
        self.stage = stage
        self.number = number  # the round's number
        self.day = day
        self.session = session
        self.zone = ZoneInfo(tournament.timezone)

    @classmethod
    def of(cls, announcement: Announcement) -> "Selection":
        return cls(
            announcement.tournament,
            announcement.scope,
            event=announcement.event,
            stage=announcement.stage,
            number=announcement.round,
            day=announcement.day,
            session=announcement.session,
        )

    def heading(self, rounds: dict) -> str:
        name = self.tournament.name
        if self.scope == Scope.EVENT:
            return f"{name}: {self.event.name} results"
        if self.scope == Scope.ROUND:
            return f"{name}: {self.event.name}, {self._round_name(rounds)} results"
        if self.scope == Scope.DAY:
            return f"{name}: results of {self.day.strftime('%A %-d %B')}"
        if self.scope == Scope.SESSION:
            label = self.session.name or f"session of {self.session.day.strftime('%A %-d %B')}"
            return f"{name}: {label} ({self.session.starts:%H:%M}-{self.session.ends:%H:%M}) results"
        return f"{name}: results"

    def _round_name(self, rounds: dict) -> str:
        if self.stage == Match.Stage.GROUP:
            return f"group stage round {self.number}"
        total = next(iter(rounds.values()), None)
        return drawing.round_name(self.number, total).lower() if total else f"round {self.number}"

    def matches(self) -> list[Match]:
        """The scope's matches, byes left out, in programme order: events as listed, then stage, round,
        group and position. A match whose sides aren't known yet is in it too, as pending."""
        found = (
            Match.objects.filter(
                draw__event__tournament=self.tournament, draw__status=DrawVersion.Status.PUBLISHED
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
            found = found.filter(stage=self.stage, round=self.number)
        if self.scope == Scope.DAY:
            start = datetime.combine(self.day, time.min, self.zone)
            end = datetime.combine(self.day, time.max, self.zone)
            decided = OfficialResult.objects.filter(
                rubber__isnull=True, current=True, first_accepted_at__range=(start, end)
            ).values("match_id")
            found = found.filter(scheduled_at__range=(start, end)) | found.filter(id__in=decided)
        if self.scope == Scope.SESSION:
            start = datetime.combine(self.session.day, self.session.starts, self.zone)
            end = datetime.combine(self.session.day, self.session.ends, self.zone)
            found = found.filter(scheduled_at__gte=start, scheduled_at__lt=end)
            events = [event.id for event in self.session.events.all()]
            if events:
                found = found.filter(draw__event_id__in=events)
        return list(found)


def generate(selection: Selection) -> tuple[str, str, list[Match]]:
    """(title, text, matches covered) for the selection, from the official results as they stand. The
    matches covered include every match of a group whose table is printed, so correcting any of them
    makes a published post out of date."""
    matches = selection.matches()
    ids = [match.id for match in matches]
    results = {
        result.match_id: result
        for result in OfficialResult.objects.filter(match_id__in=ids, rubber__isnull=True, current=True)
    }
    rubbers = _rubbers(ids)
    rounds = dict(
        Match.objects.filter(
            draw_id__in={m.draw_id for m in matches} | _selected_draws(selection), stage=Match.Stage.KNOCKOUT
        )
        .values_list("draw_id")
        .annotate(rounds=Max("round"))
    )
    by_event: dict = defaultdict(list)
    for match in matches:
        by_event[match.draw.event].append(match)

    heading = selection.heading(rounds)
    lines = [heading, ""]
    covered = list(matches)
    tables = _group_tables(by_event)
    podiums = _podiums(by_event, rounds)
    for event, played in by_event.items():
        lines.append(event.name)
        shown_round = None
        for match in played:
            here = _round_heading(match, rounds)
            if here != shown_round:
                shown_round = here
                lines.append(here)
            a, b = title(match.entry_a) or TO_BE_DECIDED, title(match.entry_b) or TO_BE_DECIDED
            result = results.get(match.id)
            decided = rubbers.get(match.id, [])
            won = None
            if event.is_team and result is not None:
                won = [
                    sum(1 for _, r, _ in decided if r.winner_id == match.entry_a_id),
                    sum(1 for _, r, _ in decided if r.winner_id == match.entry_b_id),
                ]
            a_won = result is not None and result.winner_id == match.entry_a_id
            lines.append(score_line(a, b, result, a_won, won))
            for rubber, rubber_result, names in decided:
                line = score_line(
                    names[0], names[1], rubber_result, rubber_result.winner_id == match.entry_a_id
                )
                lines.append(f"  Rubber {rubber.position}: {line}")
        event_tables, members = tables.get(event.id, ([], []))
        lines.extend(event_tables)
        covered.extend(members)
        lines.extend(podiums.get(event.id, []))
        lines.append("")
    if not matches:
        lines.append("No matches in this selection yet.")
    awards = _awards(selection)
    if awards:
        lines += ["", "Awards", *awards]
    return heading[:MAX_TITLE], _fit("\n".join(lines).strip()), covered


def _awards(selection: Selection) -> list[str]:
    """The organizers' own awards (best player, best umpire, fair play…; user request, 2026-11-28): all of
    them in an announcement of the whole tournament, those given in an event in one of that event.
    Placements are left out, since the podiums already name them. In ceremony order."""
    if selection.scope not in (Scope.TOURNAMENT, Scope.EVENT):
        return []
    found = Award.objects.filter(
        ceremony__tournament=selection.tournament, kind=Award.Kind.SPECIAL
    ).select_related("recipient", "entry")
    if selection.scope == Scope.EVENT:
        found = found.filter(event=selection.event)
    lines = []
    for award in found.prefetch_related("entry__players__user"):
        receives = (
            title(award.entry)
            if award.entry_id
            else award.recipient.display_name
            if award.recipient_id
            else award.recipient_name
        )
        line = f"{award.title}: {receives or 'to be announced'}"
        if award.prize:
            line += f" ({award.prize})"
        lines.append(line)
    return lines


def _fit(text: str) -> str:
    """The text within MAX_BODY, cut at a line and saying so, never mid-line."""
    if len(text) <= MAX_BODY:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        if sum(len(k) + 1 for k in kept) + len(line) + 60 > MAX_BODY:
            break
        kept.append(line)
    return "\n".join(
        kept + ["", f"(Shortened: {len(lines) - len(kept)} more lines. Choose a smaller selection.)"]
    )


def _selected_draws(selection: Selection) -> set:
    if selection.scope == Scope.ROUND and selection.event is not None:
        return set(
            DrawVersion.objects.filter(
                event=selection.event, status=DrawVersion.Status.PUBLISHED
            ).values_list("id", flat=True)
        )
    return set()


def _round_heading(match: Match, rounds: dict) -> str:
    if match.stage == Match.Stage.GROUP:
        return (
            f"{drawing.group_name(match.group)}, round {match.round}"
            if match.group
            else f"Round {match.round}"
        )
    return drawing.round_name(match.round, rounds.get(match.draw_id) or match.round)


def _rubbers(match_ids: list) -> dict:
    """For each tie, its decided rubbers: (rubber, current result, (side a's names, side b's names))."""
    found: dict = defaultdict(list)
    results = {
        result.rubber_id: result
        for result in OfficialResult.objects.filter(
            match_id__in=match_ids, rubber__isnull=False, current=True
        )
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


def _group_tables(by_event: dict) -> dict:
    """For each event, the tables of the groups this selection played in (an unfinished one says "so far")
    and every match of those groups. One standings computation per group printed; names in one query."""
    wanted = []
    for event, played in by_event.items():
        groups = sorted({m.group for m in played if m.stage == Match.Stage.GROUP and m.group})
        if groups:
            wanted.append((event, played[0].draw, groups))
    if not wanted:
        return {}
    computed = []
    members: set = set()
    for event, draw, groups in wanted:
        for group in groups:
            rows, complete = drawing.group_table(draw, group)
            computed.append((event, draw, group, rows, complete))
            members.update(str(row.member) for row in rows)
    names = {
        str(entry.id): title(entry)
        for entry in Entry.objects.filter(id__in=members).prefetch_related("players__user")
    }
    in_groups = Match.objects.filter(
        draw_id__in={draw.id for _, draw, _ in wanted}, stage=Match.Stage.GROUP
    ).only("id", "draw_id", "group")
    tables: dict = {}
    for event, draw, group, rows, complete in computed:
        lines, covered = tables.setdefault(event.id, ([], []))
        standing = ", ".join(
            f"{row.rank}. {names.get(str(row.member), '')} ({row.won}-{row.lost})" for row in rows
        )
        lines.append(f"{drawing.group_name(group)} table{'' if complete else ' so far'}: {standing}")
        covered.extend(m for m in in_groups if m.draw_id == draw.id and m.group == group)
    return tables


def _podiums(by_event: dict, rounds: dict) -> dict:
    """The podium of each completed event whose last match is in the selection: its final, or for an event
    without a knockout, any of its matches (the table decides it). Names in one query."""
    placed = {}
    for event, played in by_event.items():
        if event.status != Event.Status.COMPLETED:
            continue
        last = rounds.get(played[0].draw_id)
        if last and not any(m.stage == Match.Stage.KNOCKOUT and m.round == last for m in played):
            continue
        places = ceremony.podium(event)
        if places:
            placed[event.id] = places
    if not placed:
        return {}
    ids = {entry for places in placed.values() for _, entries in places for entry in entries}
    names = {
        entry.id: title(entry) for entry in Entry.objects.filter(id__in=ids).prefetch_related("players__user")
    }
    return {
        event_id: [
            f"{PLACE.get(place, f'Place {place}')}: {' and '.join(names.get(e, '') for e in entries)}"
            for place, entries in places
        ]
        for event_id, places in placed.items()
    }


def selection_from(tournament: Tournament, asked: dict) -> Selection:
    """The selection the organizers asked for, every part of it checked against the tournament."""
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
    return Selection(
        tournament,
        scope,
        event=event,
        stage=asked.get("stage") or "",
        number=asked.get("round"),
        day=asked.get("day"),
        session=session,
    )


def draft(
    tournament: Tournament, selection: Selection, actor, amends: Announcement | None = None
) -> Announcement:
    """A new draft with the generated text."""
    heading, text, matches = generate(selection)
    made = Announcement.objects.create(
        tournament=tournament,
        scope=selection.scope,
        event=selection.event,
        stage=selection.stage,
        round=selection.number,
        day=selection.day,
        session=selection.session,
        title=heading if amends is None else f"Amended: {heading}"[:MAX_TITLE],
        body=text,
        created_by=actor,
        amends=amends,
    )
    made.covers.set({match.id for match in matches})
    return made


def ensure_amendable(original: Announcement) -> None:
    """Only a published post is amended, and only once at a time: a draft amendment is edited, and a post
    already amended is amended through its amendment."""
    if original.status != Announcement.Status.PUBLISHED:
        raise ApiException("not_published", "Edit the draft itself; only a published post is amended.", 409)
    later = original.amendments.all()
    if any(a.status == Announcement.Status.DRAFT for a in later):
        raise ApiException(
            "amendment_pending", "This post already has a draft amendment: edit that one.", 409
        )
    if any(a.status == Announcement.Status.PUBLISHED for a in later):
        raise ApiException("already_amended", "This post was amended already: amend the amendment.", 409)


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
