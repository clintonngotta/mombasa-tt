"""The order of play (REQ-053, TASK-127).

Three things the organizers decide on top of the day schedule (`scheduling.py`, `publication.py`):

* The order of the stages: an event's group stage or knockout, for example men's singles groups, then
  women's singles groups, then men's singles knockout. Until staff save an order, stages carry no
  rank and the schedule and the queue behave as before. Once saved, the recommended schedule and the
  dispatch queue take stages in that order; a stage whose players are busy falls through to the next,
  so no table stands idle while a match could be played.
* When the published order of play becomes public: no earlier than three days before the first day's
  start, and no later than that start. Publishing it for the first time sets the earliest moment
  still to come; staff may choose another inside that window until it is out. Before then only staff
  see the times; at that moment every player entered is told once.
* A player's "not before": they can't play before 11:00, say, though the plan said 09:00. The
  recommendation and the checks respect it, dispatch holds their matches until then unless staff set
  it aside with a reason, and staff can move their published matches to that time in one step. A
  single match can be moved later the same way. Moves are published at once as a schedule version,
  with the usual notices once the order of play is out.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from core.exceptions import ApiException
from outbox import service as outbox

from . import matchday, scheduling
from .models import (
    DrawVersion,
    Entry,
    EntryPlayer,
    Match,
    MatchDayLog,
    NotBefore,
    ScheduleVersion,
    StageOrder,
    Tournament,
)

EARLIEST_RELEASE = timedelta(days=3)
RELEASE = "order_of_play.release"


# --- When it goes public ---------------------------------------------------------------------------


def first_start(tournament: Tournament) -> datetime:
    """When play is due to begin: the first session of the first day, or the usual day start."""
    zone = ZoneInfo(tournament.timezone)
    first = tournament.schedule_sessions.filter(day=tournament.starts_on).order_by("starts").first()
    clock = first.starts if first else scheduling.DAY_STARTS
    return datetime.combine(tournament.starts_on, clock, tzinfo=zone)


def release_window(tournament: Tournament) -> tuple[datetime, datetime]:
    start = first_start(tournament)
    return start - EARLIEST_RELEASE, start


def released(tournament: Tournament, now: datetime | None = None) -> bool:
    at = tournament.order_of_play_release_at
    return at is not None and at <= (now or timezone.now())


def times_shown(tournament: Tournament) -> bool:
    """Whether everybody may see planned starts and tables: once released, and for a tournament whose
    schedule predates release times."""
    at = tournament.order_of_play_release_at
    return at is None or at <= timezone.now()


def _schedule_release(tournament: Tournament, at: datetime) -> None:
    tournament.order_of_play_release_at = at
    tournament.save(update_fields=["order_of_play_release_at"])
    job = outbox.enqueue(
        RELEASE,
        f"{RELEASE}:{tournament.id}:{at.isoformat()}",
        {"tournament_id": str(tournament.id), "at": at.isoformat()},
    )
    if job.available_at < at:
        type(job).objects.filter(pk=job.pk).update(available_at=at)


def hold_back(tournament: Tournament) -> None:
    """On the first publication: the order of play goes public at the earliest moment allowed that is
    still to come. Call inside the publishing transaction."""
    if tournament.order_of_play_release_at is None:
        earliest, _latest = release_window(tournament)
        _schedule_release(tournament, max(earliest, timezone.now()))


def set_release(tournament: Tournament, at: datetime | None, actor) -> None:
    """Choose when the published order of play goes public; None means now."""
    if released(tournament):
        raise ApiException("already_released", "The order of play is already public.", 409)
    if not tournament.schedule_versions.exists():
        raise ApiException("nothing_published", "Publish the schedule first.", 409)
    now = timezone.now()
    earliest, latest = release_window(tournament)
    zone = ZoneInfo(tournament.timezone)
    wanted = at or now
    if wanted < earliest:
        raise serializers.ValidationError(
            {
                "release_at": "No earlier than three days before play starts: "
                f"{earliest.astimezone(zone):%a %d %b %H:%M}."
            }
        )
    if wanted > latest and latest > now:
        raise serializers.ValidationError(
            {"release_at": f"No later than the start of play: {latest.astimezone(zone):%a %d %b %H:%M}."}
        )
    _schedule_release(tournament, max(wanted, now))
    when = "now" if wanted <= now else f"at {wanted.astimezone(zone):%a %d %b %H:%M}"
    matchday.log(
        tournament, MatchDayLog.Action.ORDER_CHANGED, f"Order of play goes public {when}", actor=actor
    )


def entrants(tournament: Tournament):
    """Players holding a place in one of the tournament's events."""
    from accounts.models import User

    places = EntryPlayer.objects.filter(
        entry__event__tournament=tournament, entry__status=Entry.Status.ACCEPTED
    ).values("user_id")
    return User.objects.filter(pk__in=places).order_by("display_name")


@outbox.handler(RELEASE)
def announce(payload: dict) -> None:
    """Tell every player entered that the order of play is out, once, if this is still its release."""
    from notifications import triggers

    tournament = Tournament.objects.select_related("organization").filter(pk=payload["tournament_id"]).first()
    if tournament is None or tournament.order_of_play_announced_at is not None:
        return
    at = tournament.order_of_play_release_at
    if at is None or at.isoformat() != payload["at"] or at > timezone.now():
        return  # moved to another time: that time's job tells them
    tournament.order_of_play_announced_at = timezone.now()
    tournament.save(update_fields=["order_of_play_announced_at"])
    triggers.order_of_play_out(tournament, list(entrants(tournament)))


# --- The order of the stages -----------------------------------------------------------------------

STAGE_WORDS = {Match.Stage.GROUP: "groups", Match.Stage.KNOCKOUT: "knockout"}


def stages(tournament: Tournament) -> list[dict]:
    """Every stage that has matches in a published draw, in the saved order and then, for stages not
    placed yet, in programme order with groups before the knockout."""
    events = {event.id: event for event in tournament.events.all()}
    present = set(
        Match.objects.filter(draw__event__tournament=tournament, draw__status=DrawVersion.Status.PUBLISHED)
        .values_list("draw__event_id", "stage")
        .distinct()
    )
    placed = [
        (place.event_id, place.stage)
        for place in tournament.stage_order.all()
        if (place.event_id, place.stage) in present
    ]
    rest = sorted(
        present - set(placed),
        key=lambda key: (events[key[0]].position, events[key[0]].created_at, key[1] != Match.Stage.GROUP),
    )
    return [
        {
            "event_id": event_id,
            "event_name": events[event_id].name,
            "stage": stage,
            "label": f"{events[event_id].name}, {STAGE_WORDS[stage]}",
            "placed": (event_id, stage) in placed,
        }
        for event_id, stage in placed + rest
    ]


def ranks(tournament: Tournament) -> dict | None:
    """(event id, stage) -> place in the order, or None while staff haven't saved an order."""
    if not tournament.stage_order.exists():
        return None
    return {(row["event_id"], row["stage"]): index for index, row in enumerate(stages(tournament))}


def rank_of(found: dict | None, match: Match) -> int:
    if not found:
        return 0
    return found.get((match.draw.event_id, match.stage), len(found))


def reorder(tournament: Tournament, wanted: list[tuple], actor) -> list[dict]:
    """Save the order of the stages: every stage once. Logged with who changed it."""
    current = stages(tournament)
    keys = [(row["event_id"], row["stage"]) for row in current]
    if sorted(wanted, key=str) != sorted(keys, key=str) or len(set(wanted)) != len(wanted):
        raise serializers.ValidationError({"stages": "List every stage of the published draws once."})
    StageOrder.objects.filter(tournament=tournament).delete()
    StageOrder.objects.bulk_create(
        StageOrder(tournament=tournament, position=index, event_id=event_id, stage=stage)
        for index, (event_id, stage) in enumerate(wanted)
    )
    shown = stages(tournament)
    summary = "Order of play: " + ", then ".join(row["label"] for row in shown)
    matchday.log(tournament, MatchDayLog.Action.ORDER_CHANGED, summary, actor=actor)
    return shown


# --- Not before, and moving matches later ----------------------------------------------------------


def not_before(tournament: Tournament) -> dict:
    """Player id -> the earliest they can play."""
    return dict(NotBefore.objects.filter(tournament=tournament).values_list("user_id", "at"))


def _on_a_day(tournament: Tournament, at: datetime, field: str) -> None:
    day = at.astimezone(ZoneInfo(tournament.timezone)).date()
    if not tournament.starts_on <= day <= tournament.ends_on:
        raise serializers.ValidationError({field: "Choose a time on one of the tournament's days."})


def set_not_before(tournament: Tournament, user, at: datetime, note: str, actor, move: bool):
    """Record that `user` can't play before `at`; with `move`, publish their matches planned earlier at
    that time, and whatever then clashes later still. Returns the version published, if any."""
    if not entrants(tournament).filter(pk=user.pk).exists():
        raise ApiException("not_entered", "Choose a player entered in this tournament.", 409)
    _on_a_day(tournament, at, "at")
    NotBefore.objects.update_or_create(
        tournament=tournament, user=user, defaults={"at": at, "note": note, "set_by": actor}
    )
    zone = ZoneInfo(tournament.timezone)
    matchday.log(
        tournament,
        MatchDayLog.Action.NOT_BEFORE,
        f"{user.display_name} plays from {at.astimezone(zone):%a %H:%M}",
        actor=actor,
        reason=note,
    )
    if not move:
        return None
    theirs = {
        match.id: at
        for match in scheduling.plannable(tournament)
        if match.scheduled_at
        and match.scheduled_at < at
        and user.pk in {**scheduling._people(match.entry_a), **scheduling._people(match.entry_b)}
    }
    if not theirs:
        return None
    return move_later(tournament, actor, theirs, ScheduleVersion.Reason.PLAYER_REQUEST, note)


def clear_not_before(tournament: Tournament, user_id, actor) -> None:
    found = NotBefore.objects.filter(tournament=tournament, user_id=user_id).select_related("user").first()
    if found is None:
        raise ApiException("not_found", "Not found.", 404)
    found.delete()
    matchday.log(
        tournament,
        MatchDayLog.Action.NOT_BEFORE,
        f"{found.user.display_name} may play at any time again",
        actor=actor,
    )


def move_match(
    tournament: Tournament, match_id, at: datetime, reason: str, note: str, actor
) -> ScheduleVersion:
    """Move one published match to a later start, publishing it and what then clashes."""
    match = next((m for m in scheduling.plannable(tournament) if m.id == match_id), None)
    if match is None:
        raise ApiException(
            "not_plannable", "That match is decided, on a table, or not in this tournament.", 409
        )
    if match.scheduled_at is None:
        raise ApiException(
            "not_published", "That match has no published start yet: plan it in the schedule.", 409
        )
    if at <= match.scheduled_at:
        raise serializers.ValidationError({"scheduled_at": "Choose a time after its published start."})
    _on_a_day(tournament, at, "scheduled_at")
    version = move_later(tournament, actor, {match.id: at}, reason, note)
    zone = ZoneInfo(tournament.timezone)
    matchday.log(
        tournament,
        MatchDayLog.Action.MATCH_MOVED,
        f"{scheduling.label(match)} moved to {at.astimezone(zone):%a %H:%M}",
        actor=actor,
        match=match,
        reason=note,
    )
    return version


def move_later(tournament: Tournament, actor, starts: dict, reason: str, note: str) -> ScheduleVersion:
    """Publish `starts` (match id -> no earlier than) on the published schedule, moving on whatever then
    starts before its table, its players or the matches it waits for are free, and keeping every
    player's not-before. The working plan follows where it hadn't been changed."""
    from . import publication

    matches = scheduling.plannable(tournament)
    items = scheduling.items_for(matches)
    plans = {pk: scheduling.Plan(item, *scheduling.published(item)) for pk, item in items.items()}
    for pk, at in starts.items():
        plan = plans[pk]
        if plan.at is not None and at > plan.at:
            plan.at = scheduling._round_up(at)
    earliest = not_before(tournament)
    for plan in plans.values():
        floor = max((earliest[user] for user in plan.item.people if user in earliest), default=None)
        if plan.at is not None and floor and plan.at < floor:
            plan.at = scheduling._round_up(floor)
    scheduling.push_on(plans)
    moves = []
    for pk, plan in plans.items():
        match = items[pk].match
        if plan.at != match.scheduled_at:
            if (match.draft_table_id, match.draft_at) == (match.planned_table_id, match.scheduled_at):
                match.draft_table, match.draft_at = plan.table, plan.at
                match.save(update_fields=["draft_table", "draft_at"])
            moves.append((match, plan.table, plan.at))
    if not moves:
        raise ApiException("nothing_to_move", "Those matches already start no earlier than that.", 409)
    return publication.record(tournament, actor, ScheduleVersion.Kind.MOVED, moves, reason=reason, note=note)
