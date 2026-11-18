"""Keeping draws (REQ-009): a preview the organizers can make again and again, and its publication.

Callers hold the tournament row lock, like every other change to a tournament.
"""

import hashlib
import secrets

from django.db.models import Exists, OuterRef
from django.utils import timezone

from core.exceptions import ApiException
from ratings.elo import START
from ratings.models import Discipline, Rating
from scoring.models import EnginePhase, Scorecard

from . import draws, official, signals, standings
from .models import DrawPlace, DrawVersion, Entry, Event, Match, Rubber, Tournament
from .rules import RULES_VERSION

D = DrawVersion.Status


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def ensure_drawable(tournament: Tournament, event: Event) -> None:
    """A draw is made and published between publication of the tournament and the start of the event."""
    if tournament.status == Tournament.Status.DRAFT:
        raise _conflict("not_published", "Publish the tournament before making a draw.")
    if tournament.is_closed or event.status != Event.Status.SCHEDULED:
        raise _conflict(
            "draw_closed", f"This event is {event.get_status_display().lower()}, so its draw can't change."
        )


def accepted_ids(event: Event) -> set[str]:
    return {str(pk) for pk in event.entries.filter(status=Entry.Status.ACCEPTED).values_list("pk", flat=True)}


def rating_seeds(event: Event) -> list[str]:
    if event.seeding != Event.Seeding.RATING:
        return []
    entries = list(event.entries.filter(status=Entry.Status.ACCEPTED).prefetch_related("players"))
    if len(entries) < 2:
        return []
    discipline = Discipline.DOUBLES if event.kind == Event.Kind.DOUBLES else Discipline.SINGLES
    user_ids = {place.user_id for entry in entries for place in entry.players.all()}
    ratings = dict(
        Rating.objects.filter(discipline=discipline, user_id__in=user_ids, played__gt=0).values_list(
            "user_id", "rating"
        )
    )
    ranked = []
    for entry in entries:
        players = [place.user_id for place in entry.players.all()]
        if any(user_id in ratings for user_id in players):
            rating = sum(ratings.get(user_id, START) for user_id in players) / len(players)
            ranked.append((-rating, entry.created_at, str(entry.id)))
    limit = (
        min(draws.MAX_SEEDS, draws.bracket_size(len(entries)) // 2)
        if event.format == Event.Format.KNOCKOUT
        else draws.MAX_SEEDS
    )
    return [entry_id for _, _, entry_id in sorted(ranked)[:limit]]


def is_stale(draw: DrawVersion, places=None) -> bool:
    """The accepted entries or the event's format are no longer the ones this draw was made for."""
    if draw.status == D.SUPERSEDED:
        return False
    event = draw.event
    drawn_for = (draw.format, draw.group_count, draw.qualifiers_per_group)
    if drawn_for != (event.format, event.group_count, event.qualifiers_per_group):
        return True
    places = draw.places.all() if places is None else places
    return {str(place.entry_id) for place in places} != accepted_ids(event)


def make_preview(event: Event, actor, seeds: list[str], rng_seed: int | None = None) -> DrawVersion:
    """Draw the accepted entries and keep the result as the event's preview, replacing the last one."""
    if seeds and event.seeding == Event.Seeding.NONE:
        raise _conflict("unseeded_event", "This event is unseeded. Change its seeding to seed entries.")
    if rng_seed is None:
        rng_seed = secrets.randbelow(2**31)
    try:
        plan = draws.build(
            event.format,
            list(accepted_ids(event)),
            seeds,
            rng_seed,
            group_count=event.group_count,
            qualifiers_per_group=event.qualifiers_per_group,
        )
    except draws.DrawError as error:
        raise _conflict("draw_not_possible", str(error)) from error

    event.draws.filter(status=D.PREVIEW).delete()
    last = event.draws.order_by("-version").values_list("version", flat=True).first() or 0
    draw = DrawVersion.objects.create(
        event=event,
        version=last + 1,
        rules_version=RULES_VERSION,
        rng_seed=rng_seed,
        format=event.format,
        group_count=event.group_count,
        qualifiers_per_group=event.qualifiers_per_group,
        created_by=actor,
    )
    _save_plan(draw, plan)
    return draw


def _save_plan(draw: DrawVersion, plan: draws.Plan) -> None:
    where: dict[str, dict] = {}
    for number, members in enumerate(plan.groups, start=1):
        for position, entry in enumerate(members, start=1):
            where[entry] = {"group": number, "group_position": position}
    for line, entry in enumerate(plan.lines, start=1):
        if entry:
            where[entry] = {"bracket_position": line}
    DrawPlace.objects.bulk_create(
        DrawPlace(draw=draw, entry_id=entry, seed=plan.seeds.get(entry), **place)
        for entry, place in where.items()
    )

    knockout: dict[tuple[int, int], Match] = {}
    for planned in plan.matches:  # rounds come in order, so a feeder is always saved before its match
        a, b = planned.a, planned.b
        match = Match(
            draw=draw,
            stage=planned.stage,
            group=planned.group,
            round=planned.round,
            position=planned.position,
            entry_a_id=a.entry,
            entry_b_id=b.entry if b else None,
            feeder_a=knockout.get(a.feeder) if a.feeder else None,
            feeder_b=knockout.get(b.feeder) if b and b.feeder else None,
            status=Match.Status.SCHEDULED if b else Match.Status.BYE,
            winner_id=a.entry if b is None else None,
        )
        if a.qualifier:
            match.a_from_group, match.a_from_rank = a.qualifier
        if b and b.qualifier:
            match.b_from_group, match.b_from_rank = b.qualifier
        match.save()
        if planned.stage == Match.Stage.KNOCKOUT:
            knockout[planned.round, planned.position] = match


def publish(event: Event, actor) -> DrawVersion:
    """Make the preview the event's draw. The one published before it is kept as superseded."""
    preview = event.draws.filter(status=D.PREVIEW).first()
    if preview is None:
        raise _conflict("no_preview", "Make a draw to preview before publishing one.")
    if is_stale(preview):
        raise _conflict(
            "draw_stale", "The accepted entries or the format changed since this draw was made. Draw again."
        )
    event.draws.filter(status=D.PUBLISHED).update(status=D.SUPERSEDED)
    preview.status = D.PUBLISHED
    preview.published_by = actor
    preview.published_at = timezone.now()
    preview.save(update_fields=["status", "published_by", "published_at"])
    mark_ready(preview)
    return preview


def mark_ready(draw: DrawVersion) -> None:
    """Note the moment a match of the draw has both its sides: its waiting starts here."""
    draw.matches.filter(
        status=Match.Status.SCHEDULED,
        entry_a__isnull=False,
        entry_b__isnull=False,
        ready_since__isnull=True,
    ).update(ready_since=timezone.now())


def record_result(
    match: Match,
    winner: Entry,
    *,
    outcome: str = Match.Outcome.PLAYED,
    games=(),
    actor=None,
    source: str = official.Source.UMPIRE,
) -> None:
    """The match is decided: the winner moves into the match it feeds, and a finished group sends its
    qualifiers into the knockout. `games` are [a, b] points in playing order. Who may decide a match,
    score validation and corrections arrive with official results; this is the progression."""
    if match.draw.status != D.PUBLISHED:
        raise _conflict("draw_not_published", "Only matches of the published draw are played.")
    if match.status != Match.Status.SCHEDULED:
        raise _conflict("match_decided", "This match is already decided.")
    if match.entry_a_id is None or match.entry_b_id is None:
        raise _conflict("match_not_ready", "Both sides of this match aren't known yet.")
    if winner.id not in (match.entry_a_id, match.entry_b_id):
        raise _conflict("not_in_match", "The winner is one of the two sides of the match.")
    official.ensure_not_held(match)
    event = match.draw.event
    if event.is_team:
        # A tie has no games of its own. It is played to its end through its rubbers; or it is awarded:
        # before any rubber is decided (walkover) or part-way, when a team can't go on (retired).
        most = max(tie_score(match))
        needed = event.tie_wins_needed or 0
        any_decided = match.rubbers.exclude(status=Rubber.Status.SCHEDULED).exists()
        fits = {
            Match.Outcome.PLAYED: tie_score(match)[winner.id != match.entry_a_id] >= needed > 0,
            Match.Outcome.WALKOVER: not any_decided,
            Match.Outcome.RETIRED: any_decided and most < needed,
        }
        if games or not fits.get(outcome, False):
            raise ApiException(
                "invalid_result",
                "A tie is decided by its rubbers, or awarded when a team doesn't play or can't go on.",
                400,
            )
        # Whatever wasn't needed is not played: never scored and never rated.
        match.rubbers.filter(status=Rubber.Status.SCHEDULED).update(status=Rubber.Status.NOT_PLAYED)
    else:
        check_games(event.best_of, games, outcome, a_won=winner.id == match.entry_a_id)
    match.winner = winner
    match.status = Match.Status.COMPLETED
    match.outcome = outcome
    match.games = [list(game) for game in games]
    match.save(update_fields=["winner", "status", "outcome", "games"])
    # The official record and the work that follows from it, written with the result itself.
    official.accept(match, None, winner, outcome, match.games, actor=actor, source=source)
    _send_on(match)
    if match.stage == Match.Stage.GROUP:
        place_qualifiers(match.draw, match.group)
    mark_ready(match.draw)
    # Whatever the match held (its table, its players) is released in this same transaction.
    signals.match_decided.send(sender=Match, match=match)


def check_games(best_of: int, games, outcome: str, *, a_won: bool) -> None:
    """Refuse games (as [a, b] points) that don't fit how an individual match is said to have ended: a
    played match has exactly the games its winner needed, a walkover none, a retirement too few."""
    needed = best_of // 2 + 1
    won = sum(1 for a, b in games if (a > b) == a_won and a != b)
    lost = len(games) - won
    plausible = {
        Match.Outcome.PLAYED: won == needed and lost < needed,
        Match.Outcome.WALKOVER: not games,
        Match.Outcome.RETIRED: won < needed and lost < needed,
    }
    if not plausible.get(outcome, False):
        raise ApiException("invalid_result", "The games don't fit how this match is said to have ended.", 400)


def _send_on(match: Match) -> None:
    from . import corrections  # corrections builds on this module

    for side in ("a", "b"):
        for later in Match.objects.filter(**{f"feeder_{side}": match}).select_related("draw__event"):
            # A match played again after a correction never overwrites a later match that is in
            # question or that the organizers decided to keep as played.
            if corrections.winner_known(later, side, match.winner):
                continue
            setattr(later, f"entry_{side}", match.winner)
            later.save(update_fields=[f"entry_{side}"])


def group_table(draw: DrawVersion, group: int) -> tuple[list[standings.Row], bool]:
    """The group in ranking order (3.7.5) and whether every match in it is decided. Until then members
    nobody can separate stay level; afterwards what is left is drawn by lot. The lot's number comes
    from the draw and every score in the group, so it is the same each time the table is looked at but
    nobody can know it, or choose it, before the matches are played."""
    members = [
        str(pk)
        for pk in draw.places.filter(group=group)
        .order_by("group_position")
        .values_list("entry_id", flat=True)
    ]
    from . import ties  # ties builds on this module, so it is imported here and not at the top

    team = draw.event.is_team
    matches = list(draw.matches.filter(stage=Match.Stage.GROUP, group=group).prefetch_related("rubbers"))
    results = []
    for match in matches:
        match.draw = draw  # the draw and its event are already loaded
        if match.status != Match.Status.COMPLETED:
            continue
        if team:
            results.append(ties.result_of(match))
            continue
        a_won = match.winner_id == match.entry_a_id
        loser = match.entry_b_id if a_won else match.entry_a_id
        games = tuple((a, b) if a_won else (b, a) for a, b in match.games)
        results.append(
            standings.Result(
                str(match.winner_id),
                str(loser),
                match.outcome or Match.Outcome.PLAYED,
                games,
                best_of=draw.event.best_of,
            )
        )
    complete = len(results) == len(matches)
    scores = sorted(
        (
            str(match.id),
            str(match.winner_id),
            match.outcome,
            match.games,
            [rubber.games for rubber in match.rubbers.all()] if team else [],
        )
        for match in matches
    )
    lot = hashlib.sha256(repr((str(draw.id), draw.rng_seed, group, scores)).encode()).digest()
    rows = standings.rank(
        members, results, final=complete, lot_seed=int.from_bytes(lot[:8], "big"), team=team
    )
    return rows, complete


def place_qualifiers(draw: DrawVersion, group: int) -> None:
    """Once a group is finished, write its qualifiers into the knockout places that wait for them."""
    rows, complete = group_table(draw, group)
    if not complete:
        return
    knockout = draw.matches.filter(stage=Match.Stage.KNOCKOUT)
    for row in rows:
        knockout.filter(a_from_group=group, a_from_rank=row.rank).update(entry_a=row.member)
        knockout.filter(b_from_group=group, b_from_rank=row.rank).update(entry_b=row.member)
    # A qualifier whose first knockout match is a bye is through it now that we know who it is.
    for bye in knockout.filter(status=Match.Status.BYE, winner__isnull=True, entry_a__isnull=False):
        bye.winner_id = bye.entry_a_id
        bye.save(update_fields=["winner"])
        _send_on(bye)


def placements(draw: DrawVersion) -> list[dict]:
    """What the knockout has decided so far: the winner and runner-up once the final is played, and who
    went out in each round that is finished. Nothing is ranked that hasn't been decided."""
    by_round: dict[int, list[Match]] = {}
    for match in draw.matches.filter(stage=Match.Stage.KNOCKOUT):
        by_round.setdefault(match.round, []).append(match)
    found = []
    for number in sorted(by_round, reverse=True):
        played = [match for match in by_round[number] if match.status != Match.Status.BYE]
        if not played or any(match.status != Match.Status.COMPLETED for match in played):
            continue
        losers = [m.entry_b_id if m.winner_id == m.entry_a_id else m.entry_a_id for m in played]
        name = round_name(number, len(by_round))
        if name == "Final":
            found.append({"label": "Winner", "entry_ids": [played[0].winner_id]})
            found.append({"label": "Runner-up", "entry_ids": losers})
        else:
            found.append(
                {"label": f"Lost in the {name.lower()}{'s' if len(played) > 1 else ''}", "entry_ids": losers}
            )
    return found


def group_name(number: int) -> str:
    return f"Group {chr(64 + number)}" if number <= 26 else f"Group {number}"


def round_name(round_number: int, rounds: int) -> str:
    left = rounds - round_number
    return {0: "Final", 1: "Semi-final", 2: "Quarter-final"}.get(left) or f"Round of {2 ** (left + 1)}"


def ordinal(rank: int) -> str:
    return {1: "winner", 2: "runner-up"}.get(rank) or f"number {rank}"


def describe(draw: DrawVersion) -> dict:
    """The draw as DrawSerializer shows it."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    entries = {place.entry_id: place.entry for place in places}
    seeds = {place.entry_id: place.seed for place in places}
    matches = _matches_of(draw)
    shown = _match_describer(matches, entries, seeds, draw.event.status == Event.Status.IN_PROGRESS)
    numbers = sorted({place.group for place in places if place.group})
    return {
        "id": draw.id,
        "version": draw.version,
        "status": draw.status,
        "rules_version": draw.rules_version,
        "rng_seed": draw.rng_seed,
        "stale": is_stale(draw, places),
        "created_at": draw.created_at,
        "published_at": draw.published_at,
        "groups": [{"number": number, "name": group_name(number)} for number in numbers],
        "places": places,
        "matches": [shown(match) for match in matches],
    }


def _matches_of(draw: DrawVersion) -> list[Match]:
    """Load matches, tables, rubbers and the scoring activity needed for the draw."""
    active_sheets = Scorecard.objects.filter(state__status=EnginePhase.IN_PROGRESS, confirmed_at__isnull=True)
    return list(
        draw.matches.select_related("table")
        .prefetch_related("rubbers")
        .annotate(
            scoring_live=Exists(active_sheets.filter(match_id=OuterRef("pk")))
            | Exists(
                active_sheets.filter(rubber__match_id=OuterRef("pk"), rubber__status=Rubber.Status.SCHEDULED)
            )
        )
    )


def _match_describer(matches: list[Match], entries: dict, seeds: dict, event_in_progress: bool):
    """A function turning one of `matches` (all those of a draw) into what MatchSerializer shows."""
    by_id = {match.id: match for match in matches}
    rounds = max((match.round for match in matches if match.stage == Match.Stage.KNOCKOUT), default=0)

    def side(entry_id, feeder_id, from_group, from_rank) -> dict:
        if entry_id:
            return {"entry": entries[entry_id], "seed": seeds.get(entry_id), "awaiting": ""}
        feeder = by_id.get(feeder_id)
        if feeder and feeder.status == Match.Status.BYE:
            # Through a bye: it is simply that qualifier's place.
            from_group, from_rank, feeder = feeder.a_from_group, feeder.a_from_rank, None
        if feeder:
            awaiting = f"Winner of {round_name(feeder.round, rounds).lower()} {feeder.position}"
        else:
            awaiting = f"{group_name(from_group)} {ordinal(from_rank)}"
        return {"entry": None, "seed": None, "awaiting": awaiting}

    def shown(match: Match) -> dict:
        knockout = match.stage == Match.Stage.KNOCKOUT
        return {
            "id": match.id,
            "stage": match.stage,
            "group": match.group,
            "round": match.round,
            "round_name": round_name(match.round, rounds) if knockout else f"Round {match.round}",
            "position": match.position,
            "a": side(match.entry_a_id, match.feeder_a_id, match.a_from_group, match.a_from_rank),
            "b": None
            if match.status == Match.Status.BYE
            else side(match.entry_b_id, match.feeder_b_id, match.b_from_group, match.b_from_rank),
            "status": match.status,
            "is_live": event_in_progress and match.status == Match.Status.SCHEDULED and match.scoring_live,
            "winner_id": match.winner_id,
            "outcome": match.outcome,
            "games": match.games,
            "tie_score": list(tie_score(match)) if match.rubbers.all() else None,
            "table": match.table.label if match.table else "",
            "dispatched_at": match.dispatched_at,
            "scheduled_at": match.scheduled_at,
        }

    return shown


def tie_score(match: Match) -> tuple[int, int]:
    """Rubbers won by side a and side b of a tie."""
    won = [rubber.winner_id for rubber in match.rubbers.all() if rubber.winner_id]
    return won.count(match.entry_a_id), won.count(match.entry_b_id)


def describe_match(draw: DrawVersion, match_id) -> dict | None:
    """One match of the draw as MatchDetailSerializer shows it, or None when it isn't in this draw."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    matches = _matches_of(draw)
    match = next((found for found in matches if found.id == match_id), None)
    if match is None:
        return None
    shown = _match_describer(
        matches,
        {place.entry_id: place.entry for place in places},
        {place.entry_id: place.seed for place in places},
        draw.event.status == Event.Status.IN_PROGRESS,
    )
    # A winner of this match plays on in the match it feeds; the final feeds nothing.
    onward = next((m for m in matches if match.id in (m.feeder_a_id, m.feeder_b_id)), None)
    multiple = len({place.group for place in places if place.group}) > 1
    return {
        **shown(match),
        "group_name": group_name(match.group) if match.group and multiple else "",
        "winner_plays_in": shown(onward)["round_name"] if onward else "",
        "draw_version": draw.version,
        "match": match,
    }


def standings_of(draw: DrawVersion) -> dict:
    """The published draw's standings as StandingsSerializer shows them."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    entries = {str(place.entry_id): place.entry for place in places}
    knockout_follows = draw.format == Event.Format.GROUPS_KNOCKOUT
    qualifiers = draw.qualifiers_per_group if knockout_follows else 0
    groups = []
    for number in sorted({place.group for place in places if place.group}):
        rows, complete = group_table(draw, number)
        groups.append(
            {
                "number": number,
                "name": group_name(number),
                "complete": complete,
                "qualifiers": qualifiers,
                "rows": [
                    {
                        **{name: getattr(row, name) for name in STANDING_FIELDS},
                        "entry": entries[row.member],
                        "qualified": (row.rank <= qualifiers) if complete and knockout_follows else None,
                        "tie_break": [
                            {"among": step.among, "measure": step.measure, "value": step.value}
                            for step in row.steps
                        ],
                    }
                    for row in rows
                ],
            }
        )
    return {
        "rules_version": draw.rules_version,
        "groups": groups,
        "placements": [
            {"label": found["label"], "entries": [entries[str(pk)] for pk in found["entry_ids"]]}
            for found in placements(draw)
        ],
    }


STANDING_FIELDS = (
    "rank",
    "played",
    "won",
    "lost",
    "match_points",
    "games_won",
    "games_lost",
    "points_won",
    "points_lost",
    "level",
)
