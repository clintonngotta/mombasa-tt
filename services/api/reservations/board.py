"""The ready queue and the dispatch board (REQ-014).

The queue lists every match of the tournament that could be played now or is held up, in the order
REQ-014 fixes: planned start first (matches without one after those with one), then the one that has
waited longest since both its sides were known, then its id, so the same facts always give the same
order. Each match carries what stands in its way in the words dispatch itself would refuse it with.

The board pairs the first ready matches with the free tables. That pairing is a suggestion: sending
one goes through `service.dispatch`, which looks at everything again. Automatic dispatch, when the
organizers switch it on, sends the same suggestions by itself and never sets a check aside.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from competitions import drawing
from competitions.models import DrawVersion, Event, Match, Tournament
from facilities.models import Table

from . import control, service
from .models import Hold, Reservation, TableBlock

READY, WAITING, BLOCKED = "ready", "waiting", "blocked"
logger = logging.getLogger(__name__)


@dataclass
class Row:
    """One match in the queue."""

    match: Match
    people: list
    ready_since: datetime
    reasons: list[dict] = field(default_factory=list)
    state: str = READY
    position: int | None = None  # its rank among the matches that can be played now
    table: Table | None = None  # the free table suggested for it
    held: Table | None = None  # the table staff set aside for it: it waits for this one (TASK-153)
    rubber: object = None  # a tie's rubber whose turn it is
    called_back: bool = False  # staff took it off a table: only a person sends it out again
    umpire: object = None  # whoever scores it, who can't be playing at the same time
    stage_rank: int = 0  # its stage's place in the order of play (REQ-053); 0 for all without one

    @property
    def order(self):
        planned = self.match.scheduled_at
        return (
            self.stage_rank,
            planned is None,
            planned or self.ready_since,
            self.ready_since,
            str(self.match.id),
        )


def _reason(code: str, message: str, until=None) -> dict:
    return {"code": code, "message": message, "until": until}


def _in_play(tournament: Tournament) -> bool:
    return tournament.status == Tournament.Status.IN_PROGRESS


def _rows(tournament: Tournament) -> tuple[list[Row], int]:
    """The queue in order, and how many matches still wait for an earlier result."""
    if not _in_play(tournament):
        return [], 0
    matches = (
        Match.objects.filter(
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
            draw__event__status=Event.Status.IN_PROGRESS,
            status=Match.Status.SCHEDULED,
            dispatched_at__isnull=True,
        )
        .select_related("draw__event__tournament", "entry_a", "entry_b", "table", "held_table")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
    )
    called_back = set(
        Reservation.objects.filter(
            match__draw__event__tournament=tournament, ending=Reservation.Ending.RECALLED
        ).values_list("match_id", flat=True)
    )
    from competitions import order_of_play

    ranks = order_of_play.ranks(tournament)
    rows, to_come, now = [], 0, timezone.now()
    for match in matches:
        if match.entry_a_id is None or match.entry_b_id is None:
            to_come += 1
            continue
        event = match.draw.event
        # Waiting starts when both sides were known, and not before the event began.
        since = max(filter(None, (match.ready_since, event.started_at)), default=now)
        try:
            service.ensure_dispatchable(match)
        except service.Blocked as blocked:  # a tie without its lineups
            reasons = [_reason(blocked.blocker, blocked.message)]
            rows.append(
                Row(match, [], since, reasons, BLOCKED, stage_rank=order_of_play.rank_of(ranks, match))
            )
            continue
        people, rubber = service.people_to_hold(match)
        reasons = [
            _reason(blocked.blocker, blocked.message, blocked.until)
            for blocked in service.standing_in_the_way(match, people, rubber)
        ]
        row = Row(match, people, since, reasons, BLOCKED if reasons else READY)
        row.called_back = match.id in called_back
        row.held = match.held_table
        row.rubber = rubber
        row.umpire = service._umpire_of(match, rubber) if not reasons else None
        row.stage_rank = order_of_play.rank_of(ranks, match)
        rows.append(row)
    rows.sort(key=lambda row: row.order)
    return rows, to_come


def _free_tables(tournament: Tournament) -> list[Table]:
    """Tables nothing holds and staff haven't blocked."""
    held = Hold.objects.filter(table__venue_id=tournament.venue_id, active=True).values("table_id")
    blocked = TableBlock.objects.filter(table__venue_id=tournament.venue_id, ended_at__isnull=True)
    return list(
        Table.objects.filter(venue_id=tournament.venue_id, active=True)
        .exclude(id__in=held)
        .exclude(id__in=blocked.values("table_id"))
    )


def _suggest(rows: list[Row], free: list[Table]) -> None:
    """Give the free tables to the ready matches, in queue order. A match that shares a player with
    one ahead of it waits for that one; a match with no table left waits for a table. A match staff set
    a table aside for waits for that table, and no other match takes it (TASK-153)."""
    set_aside = {row.match.held_table_id for row in rows if row.match.held_table_id}
    free = list(free)
    going: dict = {}  # person or team id -> the row they are about to play in
    rank = 0
    for row in rows:
        if row.state != READY:
            continue
        rank += 1
        row.position = rank
        if row.called_back:
            row.state = WAITING
            row.reasons = [
                _reason("called_back", "It was called back from a table: send it from the match's page.")
            ]
            continue
        match = row.match
        # A tie's later rubbers need its other players: the whole team counts as about to play.
        teams = [match.entry_a, match.entry_b] if match.draw.event.is_team else []
        needed = [(user.id, user.display_name) for user in row.people]
        needed += [(entry.id, service.entry_title(entry)) for entry in teams]
        if row.umpire is not None:
            needed.append((row.umpire.id, f"The umpire, {row.umpire.display_name},"))
        shared = next((name for key, name in needed if key in going), None)
        if shared is not None:
            ahead = going[next(key for key, _ in needed if key in going)]
            row.state = WAITING
            row.reasons = [
                _reason(
                    "plays_earlier_match",
                    f"{shared} is in a match ahead in the queue ({_title(ahead.match)}).",
                )
            ]
            continue
        if row.held is not None:
            table = next((table for table in free if table.id == row.held.id), None)
            if table is None:
                row.state = WAITING
                row.reasons = [_reason("held_table_busy", f"It waits for {row.held.label}.")]
                continue
            row.table = table
            free.remove(table)
            for key, _ in needed:
                going[key] = row
            continue
        open_tables = [table for table in free if table.id not in set_aside]
        if not open_tables:
            row.state = WAITING
            row.reasons = [_reason("no_free_table", "Every table is in use.")]
            continue
        planned = next((table for table in open_tables if table.id == row.match.planned_table_id), None)
        row.table = planned or open_tables[0]
        free.remove(row.table)
        for key, _ in needed:
            going[key] = row


def _title(match: Match) -> str:
    return f"{service.entry_title(match.entry_a)} v {service.entry_title(match.entry_b)}"


def _label(match: Match, shape: dict) -> str:
    """ "Semi-final", "Round 2" or, when the draw has several groups, "Group B · Round 2"."""
    rounds, groups = shape.get(match.draw_id, (None, None))
    if match.stage == Match.Stage.KNOCKOUT:
        return drawing.round_name(match.round, rounds or match.round)
    if (groups or 1) > 1:
        return f"{drawing.group_name(match.group)} · Round {match.round}"
    return f"Round {match.round}"


def _idle(tournament: Tournament, rows: list[Row], to_come: int) -> str:
    """Why a free table has nothing suggested for it: the real constraint, in words."""
    if not _in_play(tournament):
        return "The tournament isn't under way."
    held_up = [row for row in rows if row.state != READY]
    if not held_up:
        if to_come:
            plural = "match waits" if to_come == 1 else "matches wait"
            return f"Nothing can be played yet: {to_come} {plural} for an earlier result."
        return "No match is waiting to be played."
    first = held_up[0]
    more = len(held_up) - 1
    rest = f" {more} more {'is' if more == 1 else 'are'} held up too." if more else ""
    return f"Next would be {_title(first.match)}, but: {first.reasons[0]['message']}{rest}"


def next_on(tournament: Tournament, table: Table) -> Row | None:
    """The match that takes this table once its match ends (REQ-053 "Next match"): the queue paired with
    the free tables as dispatch would pair them, this table counted free too. Only a recommendation:
    nothing is held, sent or confirmed."""
    rows, _to_come = _rows(tournament)
    free = _free_tables(tournament) if tournament.venue_id else []
    if all(found.id != table.id for found in free):
        free.append(table)
    _suggest(rows, free)
    return next((row for row in rows if row.table is not None and row.table.id == table.id), None)


def describe_next(row: Row | None, table: Table) -> dict | None:
    if row is None:
        return None
    match = row.match
    return {
        "table_id": table.id,
        "table": table.label,
        "match_id": match.id,
        "event_id": match.draw.event_id,
        "event_name": match.draw.event.name,
        "a": service.entry_title(match.entry_a),
        "b": service.entry_title(match.entry_b),
        "planned_at": match.scheduled_at,
    }


def table_use(tournament: Tournament, now: datetime) -> tuple[datetime | None, dict]:
    """When today's play began, and table id -> (idle since, share of today's play it was in use, 0-100)
    for this tournament's tables (REQ-053). Today is the venue's day; play starts with the day's first
    match on a table."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tournament.timezone)
    midnight = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    today = list(
        Reservation.objects.filter(
            match__draw__event__tournament=tournament, table__venue_id=tournament.venue_id
        )
        .filter(Q(released_at__isnull=True) | Q(released_at__gte=midnight))
        .values("table_id", "created_at", "released_at")
    )
    if not today:
        return tournament.started_at, {}
    began = max(midnight, min(found["created_at"] for found in today))
    span = max((now - began).total_seconds(), 1)
    use: dict = {}
    for found in today:
        start = max(found["created_at"], began)
        end = found["released_at"] or now
        idle, busy = use.get(found["table_id"], (began, 0.0))
        use[found["table_id"]] = (
            max(idle, end) if found["released_at"] else now,
            busy + max((end - start).total_seconds(), 0),
        )
    return began, {
        table_id: (idle, min(100, round(100 * busy / span))) for table_id, (idle, busy) in use.items()
    }


def _umpire_names(rows: list[Row]) -> dict:
    """Who umpires each queued match (or its tie's rubber due next), by match or rubber id, in one query."""
    from scoring.models import Scorecard

    matches = [row.match.id for row in rows if row.rubber is None]
    rubbers = [row.rubber.id for row in rows if row.rubber is not None]
    cards = Scorecard.objects.filter(Q(match_id__in=matches) | Q(rubber_id__in=rubbers), umpire__isnull=False)
    return {
        card.rubber_id or card.match_id: card.umpire.display_name for card in cards.select_related("umpire")
    }


def build(tournament: Tournament) -> dict:
    """The board as BoardSerializer shows it."""
    from .models import TableUmpire

    rows, to_come = _rows(tournament)
    free = _free_tables(tournament) if tournament.venue_id else []
    _suggest(rows, free)
    table_umpires = {
        assigned.table_id: assigned.umpire
        for assigned in TableUmpire.objects.filter(tournament=tournament).select_related("umpire")
    }
    knockout = Q(stage=Match.Stage.KNOCKOUT)
    shape = {
        found["draw_id"]: (found["rounds"], found["groups"])
        for found in Match.objects.filter(draw_id__in={row.match.draw_id for row in rows})
        .values("draw_id")
        .annotate(rounds=Max("round", filter=knockout), groups=Max("group"))
    }
    suggested = {row.table.id: row for row in rows if row.table}
    umpire_names = _umpire_names(rows)
    on_tables = {held.table_id: held for held in service.active_for(tournament)}
    idle = _idle(tournament, rows, to_come)
    blocks = control.blocks_at(tournament.venue_id) if tournament.venue_id else {}
    live_now = control.Live(list(on_tables.values()))
    now = timezone.now()
    began, used = table_use(tournament, now) if _in_play(tournament) and tournament.venue_id else (None, {})
    tables = []
    for state in service.tables_of(tournament):
        held = on_tables.get(state["id"])
        row = suggested.get(state["id"])
        blocked = blocks.get(state["id"])
        live = control.describe_table(held, live_now, now) if held else None
        tables.append(
            {
                **state,
                "state": control.table_state(blocked, live, state["free"]),
                "block": {
                    "reason": blocked.reason,
                    "reason_label": blocked.get_reason_display(),
                    "note": blocked.note,
                    "since": blocked.blocked_at,
                    "by": blocked.blocked_by.display_name if blocked.blocked_by else "",
                }
                if blocked
                else None,
                "call": live["call"] if live else None,
                "umpire": live["umpire"] if live else "",
                "score": live["score"] if live else None,
                "playing": service.describe(held) if held else None,
                "suggested_match_id": row.match.id if row else None,
                "idle_reason": idle if state["free"] and not blocked and row is None else "",
                "idle_since": (
                    used.get(state["id"], (began, 0))[0]
                    if state["free"] and not blocked and _in_play(tournament)
                    else None
                ),
                "use_today": used.get(state["id"], (None, 0))[1] if _in_play(tournament) else None,
                "table_umpire": (
                    {"id": table_umpires[state["id"]].id, "name": table_umpires[state["id"]].display_name}
                    if state["id"] in table_umpires
                    else None
                ),
                "next_up": (
                    describe_next(next_on(tournament, held.table), held.table)
                    if held is not None and live and live["finishing"]
                    else None
                ),
            }
        )
    return {
        "auto_dispatch": tournament.auto_dispatch,
        "in_play": _in_play(tournament),
        "tables": tables,
        "queue": [
            {
                "match_id": row.match.id,
                "event_id": row.match.draw.event_id,
                "event_name": row.match.draw.event.name,
                "label": _label(row.match, shape),
                "a": service.entry_title(row.match.entry_a),
                "b": service.entry_title(row.match.entry_b),
                "planned_at": row.match.scheduled_at,
                "ready_since": row.ready_since,
                "state": row.state,
                "position": row.position,
                "reasons": row.reasons,
                "suggested_table_id": row.table.id if row.table else None,
                "suggested_table": row.table.label if row.table else "",
                "held_table_id": row.held.id if row.held else None,
                "held_table": row.held.label if row.held else "",
                "umpire": umpire_names.get(row.rubber.id if row.rubber else row.match.id, ""),
            }
            for row in rows
        ],
        "to_come": to_come,
    }


# How many matches, after those going to a table now, hear they are up next.
UP_NEXT = 2


def up_next(tournament: Tournament) -> list[Row]:
    """The matches next in line once a table or a player frees up: the first ready ones in queue order
    that have no table suggested now (REQ-019 "Up next", distinct from "Called to table")."""
    rows, _to_come = _rows(tournament)
    _suggest(rows, _free_tables(tournament) if tournament.venue_id else [])
    waiting = [row for row in rows if row.position is not None and row.table is None and not row.called_back]
    return waiting[:UP_NEXT]


def announce_up_next(tournament: Tournament) -> None:
    """Tell the players of the matches next in line. Each match is announced once; being called to a
    table supersedes it. A failure here never undoes the dispatch or result that led to it."""
    from notifications import triggers

    try:
        with transaction.atomic():
            for row in up_next(tournament):
                triggers.up_next(row.match, [user.pk for user in row.people])
    except Exception:
        logger.exception("Up next alerts failed for tournament %s", tournament.id)


def run_auto(tournament: Tournament, actor=None) -> list[Reservation]:
    """Send every suggested match to its table, if the organizers switched automatic dispatch on. Each
    one is checked again by `dispatch`; one that is refused is left for a person. Call inside a
    transaction."""
    if not tournament.auto_dispatch or not _in_play(tournament) or tournament.venue_id is None:
        return []
    service.lock()
    sent, refused = [], set()
    # The suggestions of one reading share no table and no player, so they are sent without reading
    # again. A second reading only follows a refusal, which left a table free for somebody else.
    for _ in range(2):
        rows, _to_come = _rows(tournament)
        rows = [row for row in rows if row.match.id not in refused]
        _suggest(rows, _free_tables(tournament))
        before = len(refused)
        for row in rows:
            if row.table is None:
                continue
            try:
                with transaction.atomic():
                    sent.append(service.dispatch(row.match, row.table, actor, automatic=True))
            except service.Blocked:
                refused.add(row.match.id)
        if len(refused) == before:
            break
    return sent
