"""The day schedule (TASK-099, TASK-081): a recommended start time and table for every match still to be
played, which the organizers edit before keeping it, and the checks that refuse a schedule that can't
work.

The organizers' working plan is each match's `draft_table` and `draft_at`; what everybody else sees is
`planned_table` and `scheduled_at`, which only publishing (`publication.py`) changes. Days are built
of sessions when the organizers set them; without sessions every day of the tournament is one session
on the tables chosen.

Matches already on a table hold it, and their players, for their estimated length: plans are checked
against those reservations, whichever tournament at the venue made them.

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

from .models import DrawVersion, Event, Match, ScheduleSession, Tournament

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
        .select_related("draw__event", "planned_table", "draft_table", "entry_a", "entry_b")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
        .order_by("draw__event__position", "draw__event__created_at", "stage", "group", "round", "position")
    )


@dataclass
class Busy:
    """A match on a table now: its table (when it is at this venue) and people are held until about
    `until`, and its people need their rest after."""

    table: Table | None
    users: set
    until: datetime
    rest: timedelta
    label: str


def reserved(tournament: Tournament, people: set) -> list[Busy]:
    """The active reservations on this venue's tables, or holding someone who plays here."""
    from django.db.models import Q

    from reservations.models import Reservation

    found = []
    now = timezone.now()
    reservations = (
        Reservation.objects.filter(status=Reservation.Status.ACTIVE)
        .filter(Q(table__venue_id=tournament.venue_id) | Q(holds__active=True, holds__user_id__in=people))
        .distinct()
        .select_related("table", "match__draw__event")
        .prefetch_related("holds")
    )
    for reservation in reservations:
        event = reservation.match.draw.event
        found.append(
            Busy(
                table=reservation.table if reservation.table.venue_id == tournament.venue_id else None,
                users={hold.user_id for hold in reservation.holds.all() if hold.active and hold.user_id},
                until=max(now, reservation.created_at + timedelta(minutes=match_minutes(event))),
                rest=timedelta(minutes=event.rest_minutes),
                label=label(reservation.match),
            )
        )
    return found


@dataclass
class Window:
    """Hours in which matches may be planned, on these tables, for these events (None: any)."""

    start: datetime
    end: datetime
    tables: list
    events: set | None


def sessions(tournament: Tournament) -> list[ScheduleSession]:
    return list(tournament.schedule_sessions.prefetch_related("tables", "events"))


def windows(
    tournament: Tournament, tables: list[Table], day_starts: time, day_ends: time, extra_days: int = 60
) -> list[Window]:
    """The organizers' sessions, on the tables chosen; without any, every day from the first day on
    (past the last as well, so that what doesn't fit is still placed and flagged) on those tables."""
    zone = ZoneInfo(tournament.timezone)
    allowed = {table.id for table in tables}
    made = sessions(tournament)
    if made:
        found = []
        for session in made:
            own = [table for table in session.tables.all() if table.id in allowed and table.active]
            if own:
                events = {event.id for event in session.events.all()} or None
                found.append(
                    Window(
                        _at(session.day, session.starts, zone),
                        _at(session.day, session.ends, zone),
                        own,
                        events,
                    )
                )
        return sorted(found, key=lambda w: w.start)
    days = (tournament.ends_on - tournament.starts_on).days + 1 + extra_days
    return [
        Window(
            _at(tournament.starts_on + timedelta(days=n), day_starts, zone),
            _at(tournament.starts_on + timedelta(days=n), day_ends, zone),
            tables,
            None,
        )
        for n in range(days)
    ]


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
    """A start and table for every plannable match, earliest first, inside the sessions (or the day
    hours). A match no session can hold comes back without either. Nothing is saved."""
    zone = ZoneInfo(tournament.timezone)
    first_day = _at(tournament.starts_on, day_starts, zone)
    start = _round_up(max(starts_at or first_day, timezone.now(), first_day))
    items = items_for(plannable(tournament))
    order = sorted(items.values(), key=lambda i: (i.level, i.match.round, *_order_key(i.match)))
    if not tables:
        return []
    spans = [w for w in windows(tournament, tables, day_starts, day_ends) if w.end > start]

    table_free = {table.id: start for table in tables}
    person_free: dict = {}
    everyone = {user_id for item in items.values() for user_id in item.people}
    for busy in reserved(tournament, everyone):
        if busy.table and busy.table.id in table_free:
            table_free[busy.table.id] = max(table_free[busy.table.id], busy.until)
        for user_id in busy.users:
            person_free[user_id] = max(person_free.get(user_id, start), busy.until + busy.rest)
    ends: dict = {}
    slots = []
    for item in order:
        earliest = max([start, *(ends[pk] for pk in item.after if pk in ends)])
        for user_id in {**item.people, **item.maybe}:
            earliest = max(earliest, person_free.get(user_id, earliest))
        best = None
        for span in spans:
            if span.events is not None and item.match.draw.event_id not in span.events:
                continue
            if best is not None and span.start >= best[0]:
                break
            for table in span.tables:
                at = max(earliest, table_free[table.id], span.start)
                if at + item.length <= span.end and (best is None or at < best[0]):
                    best = (at, table)
        if best is None:
            slots.append(
                {"match_id": item.match.id, "table_id": None, "scheduled_at": None, "beyond_last_day": True}
            )
            continue
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


def working(item: Item) -> tuple:
    return item.match.draft_table, item.match.draft_at


def published(item: Item) -> tuple:
    return item.match.planned_table, item.match.scheduled_at


def check(tournament: Tournament, chosen: dict, plan_of=working) -> tuple[list[dict], list[dict]]:
    """Conflicts and warnings of the schedule that `chosen` (match id -> (table, start)) would make,
    with every other plannable match as `plan_of` has it (the working plan, by default)."""
    zone = ZoneInfo(tournament.timezone)
    items = items_for(plannable(tournament))
    plans = {pk: Plan(item, *(chosen.get(pk) or plan_of(item))) for pk, item in items.items()}
    return _problems(tournament, plans, items, zone)


def _problems(tournament: Tournament, plans: dict, items: dict, zone) -> tuple[list[dict], list[dict]]:
    conflicts: list[dict] = []
    warnings: list[dict] = []

    def problem(into, plan: Plan, code: str, message: str) -> None:
        into.append({"match_id": plan.item.match.id, "code": code, "message": message})

    timed = sorted((plan for plan in plans.values() if plan.at), key=lambda p: (p.at, str(p.item.match.id)))
    everyone = {user_id for plan in timed for user_id in plan.item.people}
    held = reserved(tournament, everyone) if timed else []
    spans = [
        Window(
            _at(session.day, session.starts, zone),
            _at(session.day, session.ends, zone),
            list(session.tables.all()),
            {event.id for event in session.events.all()} or None,
        )
        for session in sessions(tournament)
    ]
    for plan in timed:
        day = _local(plan.at, zone).date()
        if not tournament.starts_on <= day <= tournament.ends_on:
            problem(conflicts, plan, "outside_dates", "It is planned outside the tournament's dates.")
        for busy in held:
            if busy.table and plan.table and busy.table.id == plan.table.id and plan.at < busy.until:
                problem(
                    conflicts,
                    plan,
                    "table_in_use",
                    f"{plan.table.label} has {busy.label} on it until about "
                    f"{_local(busy.until, zone):%H:%M}.",
                )
            shared = set(plan.item.people) & busy.users
            if shared and plan.at < busy.until + busy.rest:
                name = min(plan.item.people[k] for k in shared)
                problem(
                    conflicts,
                    plan,
                    "player_on_table",
                    f"{name} is playing {busy.label} until about {_local(busy.until, zone):%H:%M}.",
                )
        if spans and not any(
            span.start <= plan.at
            and plan.end <= span.end
            and (plan.table is None or plan.table.id in {t.id for t in span.tables})
            and (span.events is None or plan.item.match.draw.event_id in span.events)
            for span in spans
        ):
            problem(
                warnings,
                plan,
                "outside_session",
                "It is planned outside the sessions set for its table and event.",
            )
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
            "table_id": match.draft_table_id,
            "scheduled_at": match.draft_at,
            "published_table_id": match.planned_table_id,
            "published_at": match.scheduled_at,
            "unpublished": (match.draft_table_id, match.draft_at)
            != (match.planned_table_id, match.scheduled_at),
        }
        for match in matches
    ]


def push_on(plans: dict) -> None:
    """Move later, never earlier, every planned match that now starts before its table is free, before
    one of its people has finished and rested, or before a match it waits for ends: what a delay sets
    off. Starts move in whole steps."""
    for _ in range(50 * len(plans) + 1):
        timed = sorted((p for p in plans.values() if p.at), key=lambda p: (p.at, str(p.item.match.id)))
        moved = False
        for index, plan in enumerate(timed):
            earliest = plan.at
            for pk in plan.item.after:
                earlier = plans.get(pk)
                if earlier and earlier.at:
                    earliest = max(earliest, earlier.end)
            for other in timed[:index]:
                if plan.table and other.table and other.table.id == plan.table.id:
                    earliest = max(earliest, other.end)
                if set(plan.item.people) & set(other.item.people):
                    earliest = max(earliest, other.end + other.item.rest)
            if earliest > plan.at:
                plan.at = _round_up(earliest)
                moved = True
                break
        if not moved:
            return
