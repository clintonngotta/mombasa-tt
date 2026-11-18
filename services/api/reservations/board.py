"""The ready queue and the dispatch board (REQ-014).

The queue lists every match of the tournament that could be played now or is held up, in the order
REQ-014 fixes: planned start first (matches without one after those with one), then the one that has
waited longest since both its sides were known, then its id, so the same facts always give the same
order. Each match carries what stands in its way in the words dispatch itself would refuse it with.

The board pairs the first ready matches with the free tables. That pairing is a suggestion: sending
one goes through `service.dispatch`, which looks at everything again. Automatic dispatch, when the
organizers switch it on, sends the same suggestions by itself and never sets a check aside.
"""

from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from competitions import drawing
from competitions.models import DrawVersion, Event, Match, Tournament
from facilities.models import Table

from . import service
from .models import Hold, Reservation

READY, WAITING, BLOCKED = "ready", "waiting", "blocked"


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
    called_back: bool = False  # staff took it off a table: only a person sends it out again
    umpire: object = None  # whoever scores it, who can't be playing at the same time

    @property
    def order(self):
        planned = self.match.scheduled_at
        return (planned is None, planned or self.ready_since, self.ready_since, str(self.match.id))


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
        .select_related("draw__event__tournament", "entry_a", "entry_b", "table")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
    )
    called_back = set(
        Reservation.objects.filter(
            match__draw__event__tournament=tournament, ending=Reservation.Ending.RECALLED
        ).values_list("match_id", flat=True)
    )
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
            rows.append(Row(match, [], since, reasons, BLOCKED))
            continue
        people, rubber = service.people_to_hold(match)
        reasons = [
            _reason(blocked.blocker, blocked.message, blocked.until)
            for blocked in service.standing_in_the_way(match, people, rubber)
        ]
        row = Row(match, people, since, reasons, BLOCKED if reasons else READY)
        row.called_back = match.id in called_back
        row.umpire = service._umpire_of(match, rubber) if not reasons else None
        rows.append(row)
    rows.sort(key=lambda row: row.order)
    return rows, to_come


def _free_tables(tournament: Tournament) -> list[Table]:
    held = Hold.objects.filter(table__venue_id=tournament.venue_id, active=True).values("table_id")
    return list(Table.objects.filter(venue_id=tournament.venue_id, active=True).exclude(id__in=held))


def _suggest(rows: list[Row], free: list[Table]) -> None:
    """Give the free tables to the ready matches, in queue order. A match that shares a player with
    one ahead of it waits for that one; a match with no table left waits for a table."""
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
        needed += [(entry.id, service._entry_title(entry)) for entry in teams]
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
        if not free:
            row.state = WAITING
            row.reasons = [_reason("no_free_table", "Every table is in use.")]
            continue
        planned = next((table for table in free if table.id == row.match.planned_table_id), None)
        row.table = planned or free[0]
        free.remove(row.table)
        for key, _ in needed:
            going[key] = row


def _title(match: Match) -> str:
    return f"{service._entry_title(match.entry_a)} v {service._entry_title(match.entry_b)}"


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


def build(tournament: Tournament) -> dict:
    """The board as BoardSerializer shows it."""
    rows, to_come = _rows(tournament)
    free = _free_tables(tournament) if tournament.venue_id else []
    _suggest(rows, free)
    knockout = Q(stage=Match.Stage.KNOCKOUT)
    shape = {
        found["draw_id"]: (found["rounds"], found["groups"])
        for found in Match.objects.filter(draw_id__in={row.match.draw_id for row in rows})
        .values("draw_id")
        .annotate(rounds=Max("round", filter=knockout), groups=Max("group"))
    }
    suggested = {row.table.id: row for row in rows if row.table}
    on_tables = {held.table_id: held for held in service.active_for(tournament)}
    idle = _idle(tournament, rows, to_come)
    tables = []
    for state in service.tables_of(tournament):
        held = on_tables.get(state["id"])
        row = suggested.get(state["id"])
        tables.append(
            {
                **state,
                "playing": service.describe(held) if held else None,
                "suggested_match_id": row.match.id if row else None,
                "idle_reason": idle if state["free"] and row is None else "",
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
                "a": service._entry_title(row.match.entry_a),
                "b": service._entry_title(row.match.entry_b),
                "planned_at": row.match.scheduled_at,
                "ready_since": row.ready_since,
                "state": row.state,
                "position": row.position,
                "reasons": row.reasons,
                "suggested_table_id": row.table.id if row.table else None,
                "suggested_table": row.table.label if row.table else "",
            }
            for row in rows
        ],
        "to_come": to_come,
    }


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
