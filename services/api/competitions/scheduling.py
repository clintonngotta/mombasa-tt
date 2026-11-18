"""The day schedule (TASK-099): a recommended start time and table for every match still to be played,
which the organizers edit before keeping it, and the checks that refuse a schedule that can't work.

A match takes an estimated number of minutes from its best-of. Nobody plays two matches at once or
without the event's rest in between, a table holds one match at a time, and a match never starts
before the matches it waits for (the ones whose winners or group places fill its sides) have ended.

Who plays a match whose sides aren't known yet is uncertain: it is anybody who could still get there.
The recommendation keeps those people apart as well, and a check reports an overlap among them as a
warning rather than a conflict, because it may never happen.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from facilities.models import Table

from .models import DrawVersion, Event, Match, Tournament

MINUTES_BY_BEST_OF = {1: 10, 3: 20, 5: 30, 7: 40}
DAY_STARTS = time(9, 0)
DAY_ENDS = time(21, 0)
STEP = timedelta(minutes=5)


def match_minutes(event: Event) -> int:
    return MINUTES_BY_BEST_OF.get(event.best_of, 6 * event.best_of)


@dataclass
class Item:
    """One match to schedule and what it depends on."""

    match: Match
    minutes: int
    rest: timedelta
    people: dict  # user id -> name, certain to play it
    maybe: dict  # user id -> name, who could still reach it
    after: list = field(default_factory=list)  # ids of the matches it waits for
    level: int = 0

    @property
    def length(self) -> timedelta:
        return timedelta(minutes=self.minutes)


def _people(entry) -> dict:
    return {place.user_id: place.user.display_name for place in entry.players.all()} if entry else {}


def _title(match: Match) -> str:
    def side(entry):
        return " / ".join(place.user.display_name for place in entry.players.all()) if entry else "To come"

    return f"{side(match.entry_a)} v {side(match.entry_b)}"


def label(match: Match) -> str:
    event = match.draw.event.name
    if match.stage == Match.Stage.GROUP:
        return f"{event}, group {chr(64 + (match.group or 1))} round {match.round}"
    return f"{event}, round {match.round} match {match.position}"


def plannable(tournament: Tournament) -> list[Match]:
    """Matches of published draws that are still to be played and aren't on a table yet."""
    return list(
        Match.objects.filter(
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
            draw__event__status__in=[Event.Status.SCHEDULED, Event.Status.IN_PROGRESS],
            status=Match.Status.SCHEDULED,
            dispatched_at__isnull=True,
        )
        .select_related("draw__event", "planned_table", "entry_a", "entry_b")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
        .order_by("draw__event__position", "draw__event__created_at", "stage", "group", "round", "position")
    )


def on_tables(tournament: Tournament) -> list[Match]:
    return list(
        Match.objects.filter(
            draw__event__tournament=tournament, status=Match.Status.SCHEDULED, dispatched_at__isnull=False
        )
        .select_related("draw__event")
        .prefetch_related("entry_a__players", "entry_b__players")
    )


def items_for(matches: list[Match]) -> dict:
    """Each match with its length, its people and the matches it waits for."""
    by_id = {match.id: match for match in matches}
    group_matches: dict = {}
    for match in matches:
        if match.stage == Match.Stage.GROUP:
            group_matches.setdefault((match.draw_id, match.group), []).append(match.id)
    items = {}
    for match in matches:
        event = match.draw.event
        people = {**_people(match.entry_a), **_people(match.entry_b)}
        after = [pk for pk in (match.feeder_a_id, match.feeder_b_id) if pk in by_id]
        for group in (match.a_from_group, match.b_from_group):
            if group is not None:
                after += group_matches.get((match.draw_id, group), [])
        items[match.id] = Item(
            match=match,
            minutes=match_minutes(event),
            rest=timedelta(minutes=event.rest_minutes),
            people=people,
            maybe={},
            after=after,
        )

    def settle(item: Item, seen: set) -> None:
        if item.match.id in seen:
            return
        seen.add(item.match.id)
        for pk in item.after:
            settle(items[pk], seen)
        if item.after:
            item.level = 1 + max(items[pk].level for pk in item.after)
            for pk in item.after:
                earlier = items[pk]
                item.maybe.update({**earlier.people, **earlier.maybe})
            for user_id in item.people:
                item.maybe.pop(user_id, None)

    done: set = set()
    for item in items.values():
        settle(item, done)
    return items


def _local(moment: datetime, zone: ZoneInfo) -> datetime:
    return moment.astimezone(zone)


def _at(day: date, clock: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=zone)


def _round_up(moment: datetime) -> datetime:
    seconds = STEP.total_seconds()
    stamp = moment.timestamp()
    return datetime.fromtimestamp(-(-stamp // seconds) * seconds, tz=moment.tzinfo)


def recommend(
    tournament: Tournament,
    tables: list[Table],
    *,
    starts_at: datetime | None = None,
    day_starts: time = DAY_STARTS,
    day_ends: time = DAY_ENDS,
) -> list[dict]:
    """A start and table for every plannable match, earliest first. Nothing is saved."""
    zone = ZoneInfo(tournament.timezone)
    first_day = _at(tournament.starts_on, day_starts, zone)
    start = _round_up(max(starts_at or first_day, timezone.now(), first_day))
    items = items_for(plannable(tournament))
    order = sorted(items.values(), key=lambda i: (i.level, i.match.round, *_order_key(i.match)))
    if not tables:
        return []

    def into_day(moment: datetime, length: timedelta) -> datetime:
        local = _local(moment, zone)
        opens = _at(local.date(), day_starts, zone)
        if local < opens:
            return opens
        if local + length > _at(local.date(), day_ends, zone):
            return _at(local.date() + timedelta(days=1), day_starts, zone)
        return moment

    table_free = {table.id: start for table in tables}
    person_free: dict = {}
    # Matches on a table now keep it, and their players, for their estimated length.
    for match in on_tables(tournament):
        busy_until = max(start, match.dispatched_at + timedelta(minutes=match_minutes(match.draw.event)))
        if match.table_id in table_free:
            table_free[match.table_id] = max(table_free[match.table_id], busy_until)
        for user_id in {**_people(match.entry_a), **_people(match.entry_b)}:
            person_free[user_id] = busy_until + timedelta(minutes=match.draw.event.rest_minutes)
    ends: dict = {}
    slots = []
    for item in order:
        earliest = max([start, *(ends[pk] for pk in item.after if pk in ends)])
        for user_id in {**item.people, **item.maybe}:
            earliest = max(earliest, person_free.get(user_id, earliest))
        best = None
        for table in tables:
            at = into_day(max(earliest, table_free[table.id]), item.length)
            if best is None or at < best[0]:
                best = (at, table)
        at, table = best
        end = at + item.length
        table_free[table.id] = end
        ends[item.match.id] = end
        for user_id in {**item.people, **item.maybe}:
            person_free[user_id] = end + item.rest
        slots.append(
            {
                "match_id": item.match.id,
                "table_id": table.id,
                "scheduled_at": at,
                "beyond_last_day": _local(at, zone).date() > tournament.ends_on,
            }
        )
    return slots


def _order_key(match: Match) -> tuple:
    event = match.draw.event
    return (event.position, event.created_at, match.stage, match.group or 0, match.position)


@dataclass
class Plan:
    item: Item
    table: Table | None
    at: datetime | None

    @property
    def end(self) -> datetime:
        return self.at + self.item.length


def check(tournament: Tournament, chosen: dict) -> tuple[list[dict], list[dict]]:
    """Conflicts and warnings of the schedule that `chosen` (match id -> (table, start)) would make,
    with every other plannable match as it is now planned."""
    zone = ZoneInfo(tournament.timezone)
    items = items_for(plannable(tournament))
    plans = {
        pk: Plan(item, *(chosen.get(pk) or (item.match.planned_table, item.match.scheduled_at)))
        for pk, item in items.items()
    }
    conflicts: list[dict] = []
    warnings: list[dict] = []

    def problem(into, plan: Plan, code: str, message: str) -> None:
        into.append({"match_id": plan.item.match.id, "code": code, "message": message})

    timed = sorted((plan for plan in plans.values() if plan.at), key=lambda p: (p.at, str(p.item.match.id)))
    for plan in timed:
        day = _local(plan.at, zone).date()
        if not tournament.starts_on <= day <= tournament.ends_on:
            problem(conflicts, plan, "outside_dates", "It is planned outside the tournament's dates.")
        for pk in plan.item.after:
            earlier = plans[pk]
            if earlier.at and plan.at < earlier.end:
                problem(
                    conflicts,
                    plan,
                    "before_earlier_match",
                    f"It starts before {label(earlier.item.match)} ends, and its players come from there.",
                )
    for index, plan in enumerate(timed):
        for other in timed[index + 1 :]:
            if other.at >= plan.end + plan.item.rest:
                break
            overlapping = other.at < plan.end
            if overlapping and plan.table and other.table and plan.table.id == other.table.id:
                problem(
                    conflicts,
                    other,
                    "table_taken",
                    f"{plan.table.label} still has {label(plan.item.match)} until "
                    f"{_local(plan.end, zone):%H:%M}.",
                )
            rested = other.at >= plan.end + plan.item.rest
            if rested:
                continue
            shared = set(plan.item.people) & set(other.item.people)
            if shared:
                name = min(plan.item.people[k] for k in shared)
                problem(
                    conflicts,
                    other,
                    "player_busy",
                    f"{name} plays {label(plan.item.match)} until {_local(plan.end, zone):%H:%M}"
                    + ("." if overlapping else f" and needs {plan.item.rest.seconds // 60} minutes' rest."),
                )
                continue
            everyone_a = {**plan.item.people, **plan.item.maybe}
            everyone_b = {**other.item.people, **other.item.maybe}
            maybe = set(everyone_a) & set(everyone_b)
            if maybe and plan.item.match.id not in _ancestors(other.item, items):
                name = min(everyone_a[k] for k in maybe)
                problem(
                    warnings,
                    other,
                    "player_may_be_busy",
                    f"{name} may be playing {label(plan.item.match)} until {_local(plan.end, zone):%H:%M}.",
                )
    return conflicts, warnings


def _ancestors(item: Item, items: dict) -> set:
    found: set = set()
    stack = list(item.after)
    while stack:
        pk = stack.pop()
        if pk not in found:
            found.add(pk)
            stack.extend(items[pk].after)
    return found


def rows(tournament: Tournament) -> list[dict]:
    """The plannable matches as they are planned now, for the schedule editor."""
    matches = plannable(tournament)
    items = items_for(matches)
    return [
        {
            "match_id": match.id,
            "event_id": match.draw.event_id,
            "event": match.draw.event.name,
            "label": label(match),
            "title": _title(match),
            "minutes": items[match.id].minutes,
            "table_id": match.planned_table_id,
            "scheduled_at": match.scheduled_at,
        }
        for match in matches
    ]
