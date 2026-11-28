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
A side still to come is one place ("Group A winner", "Winner of quarter-final 2"), so within a draw two
such matches never share a player unless one feeds the other. Across draws the recommendation keeps
those people apart as well, and a check reports an overlap among them as a warning rather than a
conflict, because it may never happen.

The top seeds don't open the day: their first matches start after the first two rounds of the tables.
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
TOP_SEEDS = 4  # at least the first four seeds of a draw, or one per group when there are more groups
SEEDS_WAIT = (5, 10)  # top seeds start after this many matches: two rounds of the tables, within it


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
    top_seeds: set = field(default_factory=set)  # entry ids of the top seeds it has

    @property
    def length(self) -> timedelta:
        return timedelta(minutes=self.minutes)


def _people(entry) -> dict:
    return {place.user_id: place.user.display_name for place in entry.players.all()} if entry else {}


def _rounds(match: Match, known: dict | None) -> int:
    """How many knockout rounds the match's draw has, asked once per draw when `known` is shared."""
    known = {} if known is None else known
    if match.draw_id not in known:
        known[match.draw_id] = (
            Match.objects.filter(draw_id=match.draw_id, stage=Match.Stage.KNOCKOUT)
            .order_by("-round")
            .values_list("round", flat=True)
            .first()
            or 0
        )
    return known[match.draw_id]


def _awaiting(match: Match, feeder: Match | None, group, rank, known: dict | None) -> str:
    """A side still to come as the draw names it: "Group A winner", "Winner of quarter-final 2"."""
    from .drawing import group_name, ordinal, round_name

    if feeder is not None and feeder.status == Match.Status.BYE:
        group, rank, feeder = feeder.a_from_group, feeder.a_from_rank, None
    if feeder is not None:
        return f"Winner of {round_name(feeder.round, _rounds(match, known)).lower()} {feeder.position}"
    if group is not None and rank is not None:
        return f"{group_name(group)} {ordinal(rank)}"
    return "To come"


def _title(match: Match, known: dict | None = None) -> str:
    def side(entry, feeder_id, group, rank, feeder):
        if entry:
            return " / ".join(place.user.display_name for place in entry.players.all())
        return _awaiting(match, feeder() if feeder_id else None, group, rank, known)

    a = side(match.entry_a, match.feeder_a_id, match.a_from_group, match.a_from_rank, lambda: match.feeder_a)
    b = side(match.entry_b, match.feeder_b_id, match.b_from_group, match.b_from_rank, lambda: match.feeder_b)
    return f"{a} v {b}"


def label(match: Match, known: dict | None = None) -> str:
    from .drawing import round_name

    event = match.draw.event.name
    if match.stage == Match.Stage.GROUP:
        return f"{event}, group {chr(64 + (match.group or 1))} round {match.round}"
    name = round_name(match.round, _rounds(match, known))
    return f"{event}, {name}" if name == "Final" else f"{event}, {name.lower()} {match.position}"


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
        .select_related(
            "draw__event", "planned_table", "draft_table", "entry_a", "entry_b", "feeder_a", "feeder_b"
        )
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
    tournament: Tournament,
    tables: list[Table],
    day_starts: time,
    day_ends: time,
    extra_days: int = 60,
    use_sessions: bool = True,
) -> list[Window]:
    """The organizers' sessions, on the tables chosen. Without any, or when the organizers plan by the
    day's hours instead (`use_sessions` False): those hours on every day from the first day on, past
    the last as well, so that what doesn't fit is still placed and flagged."""
    zone = ZoneInfo(tournament.timezone)
    allowed = {table.id for table in tables}
    made = sessions(tournament) if use_sessions else []
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
    top = top_seeds(matches)
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
            top_seeds={pk for pk in (match.entry_a_id, match.entry_b_id) if pk in top},
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


def top_seeds(matches: list[Match]) -> set:
    """The entries that are top seeds of their draws: the first seeds, one per group (at least four)."""
    from .models import DrawPlace

    draws = {match.draw_id: match.draw for match in matches}
    found = set()
    for place in DrawPlace.objects.filter(draw_id__in=draws, seed__isnull=False).values(
        "draw_id", "entry_id", "seed"
    ):
        if place["seed"] <= max(TOP_SEEDS, draws[place["draw_id"]].group_count or 0):
            found.add(place["entry_id"])
    return found


def seeds_wait(tables: list) -> int:
    """How many matches start before a top seed plays: two rounds of the tables, from five to ten."""
    return min(SEEDS_WAIT[1], max(SEEDS_WAIT[0], 2 * len(tables)))


def _seeds_later(order: list[Item], wait: int) -> list[Item]:
    """`order` with each top seed's first match moved behind the first `wait` matches, as organizers
    do: the top seeds don't open the day. A match waiting for a moved one still comes after it."""
    played: set = set()
    held: list[Item] = []
    moved: set = set()
    found: list[Item] = []

    def let_go() -> None:
        while held:
            item = held.pop(0)
            found.append(item)
            played.update(item.top_seeds)

    for item in order:
        if len(found) >= wait or any(pk in moved for pk in item.after):
            let_go()
        if len(found) < wait and item.top_seeds - played:
            held.append(item)
            moved.add(item.match.id)
            continue
        found.append(item)
        played.update(item.top_seeds)
    let_go()
    return found


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
    use_sessions: bool = True,
) -> list[dict]:
    """A start and table for every plannable match, earliest first, inside the sessions (or the day's
    hours, every day). Earliest first fills the first day before the next: a one-day tournament plays
    everything that day if it fits, a longer one plays as much as it can on its first days. What
    doesn't fit in the tournament's days is placed after them and flagged; a match no session can hold
    comes back without table or start. Nothing is saved."""
    from . import order_of_play

    zone = ZoneInfo(tournament.timezone)
    first_day = _at(tournament.starts_on, day_starts, zone)
    start = _round_up(max(starts_at or first_day, timezone.now(), first_day))
    items = items_for(plannable(tournament))
    if not tables:
        return []
    order = _seeds_later(_in_order(items, order_of_play.ranks(tournament)), seeds_wait(tables))
    spans = [
        w
        for w in windows(tournament, tables, day_starts, day_ends, use_sessions=use_sessions)
        if w.end > start
    ]

    table_free = {table.id: start for table in tables}
    # A player who can't play before a time is free from then (REQ-053).
    person_free: dict = {
        user_id: max(at, start) for user_id, at in order_of_play.not_before(tournament).items()
    }
    everyone = {user_id for item in items.values() for user_id in item.people}
    for busy in reserved(tournament, everyone):
        if busy.table and busy.table.id in table_free:
            table_free[busy.table.id] = max(table_free[busy.table.id], busy.until)
        for user_id in busy.users:
            person_free[user_id] = max(person_free.get(user_id, start), busy.until + busy.rest)
    # Who might play a match whose sides aren't known yet is held apart only from other draws: in one
    # draw, a player reaches two matches only when one feeds the other, which `after` and the rest
    # after it already keep apart. Holding them in their own draw too would keep, say, every
    # quarter-final off the tables while any of them is played.
    maybe_free: dict = {}  # user id -> draw id -> free from
    ends: dict = {}
    slots = []
    for item in order:
        draw_id = item.match.draw_id
        earliest = max([start, *(ends[pk] + items[pk].rest for pk in item.after if pk in ends)])
        for user_id in {**item.people, **item.maybe}:
            earliest = max(earliest, person_free.get(user_id, earliest))
            for other, free in maybe_free.get(user_id, {}).items():
                if other != draw_id:
                    earliest = max(earliest, free)
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
        for user_id in item.people:
            person_free[user_id] = end + item.rest
        for user_id in item.maybe:
            held = maybe_free.setdefault(user_id, {})
            held[draw_id] = max(held.get(draw_id, start), end + item.rest)
        slots.append(
            {
                "match_id": item.match.id,
                "table_id": table.id,
                "scheduled_at": at,
                "beyond_last_day": _local(at, zone).date() > tournament.ends_on,
            }
        )
    return slots


def days_of(tournament: Tournament, slots: list[dict]) -> list[dict]:
    """How a recommendation fills each of the tournament's days: matches, first start and last end."""
    zone = ZoneInfo(tournament.timezone)
    lengths = {pk: item.length for pk, item in items_for(plannable(tournament)).items()}
    found = {
        tournament.starts_on + timedelta(days=n): {"matches": 0, "first_start": None, "last_end": None}
        for n in range((tournament.ends_on - tournament.starts_on).days + 1)
    }
    for slot in slots:
        at = slot["scheduled_at"]
        if at is None:
            continue
        day = found.get(_local(at, zone).date())
        if day is None:
            continue
        end = at + lengths.get(slot["match_id"], timedelta(0))
        day["matches"] += 1
        day["first_start"] = min(filter(None, (day["first_start"], at)))
        day["last_end"] = max(filter(None, (day["last_end"], end)))
    return [{"day": day, **numbers} for day, numbers in sorted(found.items())]


def _in_order(items: dict, ranks: dict | None) -> list[Item]:
    """The matches in the order they are given starts: by stage in the order of play when staff saved
    one, then by how deep in the draw, round and position; a match always after those it waits for."""
    from . import order_of_play

    def key(item: Item) -> tuple:
        return (
            order_of_play.rank_of(ranks, item.match),
            item.level,
            item.match.round,
            *_order_key(item.match),
        )

    waiting = sorted(items.values(), key=key)
    placed: set = set()
    order = []
    while waiting:
        index = next((n for n, item in enumerate(waiting) if all(pk in placed for pk in item.after)), 0)
        item = waiting.pop(index)
        placed.add(item.match.id)
        order.append(item)
    return order


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
    from .models import NotBefore

    earliest = {found.user_id: found.at for found in NotBefore.objects.filter(tournament=tournament)}
    for plan in timed:
        day = _local(plan.at, zone).date()
        if not tournament.starts_on <= day <= tournament.ends_on:
            problem(conflicts, plan, "outside_dates", "It is planned outside the tournament's dates.")
        late = [user for user in plan.item.people if user in earliest and plan.at < earliest[user]]
        if late:
            name = min(plan.item.people[user] for user in late)
            problem(
                conflicts,
                plan,
                "player_not_before",
                f"{name} can't play before {_local(max(earliest[u] for u in late), zone):%a %H:%M}.",
            )
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
            # In one draw, two matches share a player only when one feeds the other.
            same_draw = plan.item.match.draw_id == other.item.match.draw_id
            if maybe and not same_draw and plan.item.match.id not in _ancestors(other.item, items):
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
    known: dict = {}
    return [
        {
            "match_id": match.id,
            "event_id": match.draw.event_id,
            "event": match.draw.event.name,
            "label": label(match, known),
            "title": _title(match, known),
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
