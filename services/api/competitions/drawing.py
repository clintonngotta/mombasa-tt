"""Keeping draws (REQ-009): a preview the organizers can make again and again, and its publication.

Callers hold the tournament row lock, like every other change to a tournament.
"""

import secrets

from django.utils import timezone

from core.exceptions import ApiException

from . import draws
from .models import DrawPlace, DrawVersion, Entry, Event, Match, Tournament
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
    return preview


def record_winner(match: Match, winner: Entry) -> None:
    """The match is decided: the winner moves into the match it feeds. Results themselves (scores,
    walkovers, corrections) arrive with official results; this is only the progression."""
    if match.draw.status != D.PUBLISHED:
        raise _conflict("draw_not_published", "Only matches of the published draw are played.")
    if match.status != Match.Status.SCHEDULED:
        raise _conflict("match_decided", "This match is already decided.")
    if match.entry_a_id is None or match.entry_b_id is None:
        raise _conflict("match_not_ready", "Both sides of this match aren't known yet.")
    if winner.id not in (match.entry_a_id, match.entry_b_id):
        raise _conflict("not_in_match", "The winner is one of the two sides of the match.")
    match.winner = winner
    match.status = Match.Status.COMPLETED
    match.save(update_fields=["winner", "status"])
    Match.objects.filter(feeder_a=match).update(entry_a=winner)
    Match.objects.filter(feeder_b=match).update(entry_b=winner)


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
    matches = list(draw.matches.all())
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
            "winner_id": match.winner_id,
        }

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
