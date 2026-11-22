"""The match-day control centre (REQ-043), on top of dispatch.

Each table is in one state: free, called (its match was sent and not every side has reported), warming
up (both sides are at the table, no point scored yet), in play (scoring has started) or blocked (staff
took it out of use, with a reason). A side that hasn't reported within its event's grace period of the
first call is flagged as a no-show; the flag is a fact for the referee, who alone may then award a
walkover through the results desk. Every action here is written to the match-day log in the
transaction of the action itself.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from competitions import matchday
from competitions.models import Entry, Event, Match, Rubber, Tournament
from core.exceptions import ApiException
from facilities.models import Table

from . import service
from .models import Hold, MatchCall, Reservation, TableBlock

FREE, CALLED, WARMING_UP, IN_PLAY, BLOCKED = "free", "called", "warming_up", "in_play", "blocked"
SIDES = ("a", "b")
Action = matchday.Action


def active_reservation(match: Match) -> Reservation:
    reservation = match.reservations.filter(status=Reservation.Status.ACTIVE).select_related("table").first()
    if reservation is None:
        raise service.Blocked("not_on_table", "This match isn't on a table.")
    return reservation


def entry_on(match: Match, side: str) -> Entry:
    return match.entry_a if side == "a" else match.entry_b


def side_players(match: Match, reservation: Reservation, side: str) -> list:
    """The held players of one side: the entry's players, or for a tie those of the current rubber."""
    entry = entry_on(match, side)
    team = {place.user_id for place in entry.players.all()}
    held = reservation.holds.filter(active=True, user__isnull=False).select_related("user")
    return [hold.user for hold in held if hold.user_id in team]


def call_again(match: Match, actor) -> MatchCall:
    """Call the match to its table once more: the players of each side not yet at the table hear it
    again. The grace period still runs from the first call."""
    reservation = active_reservation(match)
    if in_play(match):
        raise ApiException("already_playing", "This match is being played.", 409)
    call = MatchCall.objects.create(match=match, reservation=reservation, called_by=actor)
    waiting = [
        user.pk
        for side in SIDES
        if getattr(reservation, f"{side}_reported_at") is None
        for user in side_players(match, reservation, side)
    ]
    from notifications import triggers

    triggers.called_to_table(match, reservation, waiting, version=f"call:{call.id}")
    matchday.log(
        match.draw.event.tournament_id,
        Action.CALLED_AGAIN,
        f"{matchday.match_title(match)} on {reservation.table.label}",
        actor=actor,
        match=match,
        table=reservation.table,
    )
    return call


def report(match: Match, side: str, actor, *, undo: bool = False) -> Reservation:
    """A called side is at the table (or, with `undo`, isn't after all)."""
    reservation = active_reservation(match)
    field = f"{side}_reported_at"
    if undo and in_play(match):
        raise ApiException("already_playing", "This match is being played.", 409)
    changed = (getattr(reservation, field) is None) != undo
    if not changed:
        return reservation
    setattr(reservation, field, None if undo else timezone.now())
    reservation.save(update_fields=[field])
    entry = entry_on(match, side)
    matchday.log(
        match.draw.event.tournament_id,
        Action.REPORT_UNDONE if undo else Action.REPORTED,
        f"{matchday.entry_title(entry)} at {reservation.table.label}",
        actor=actor,
        match=match,
        table=reservation.table,
    )
    return reservation


def move(match: Match, table: Table, actor, reason: str) -> Reservation:
    """Move a match that is on a table to another free table, keeping its call and who has reported.
    Everything dispatch checks is checked again for the new table. Call inside a transaction."""
    old = active_reservation(match)
    if old.table_id == table.id:
        raise ApiException("same_table", "The match is already on that table.", 409)
    service.lock()
    service.release(old, actor, Reservation.Ending.MOVED, reason)
    service.off_the_table(match)
    # The players were at a table a moment ago: dispatch's check-in and rest checks still apply, but a
    # match that went out with them set aside keeps what was set aside.
    new = service.dispatch(
        match,
        table,
        actor,
        overrides=old.overrides,
        reason=old.override_reason,
        automatic=old.automatic,
        carry=old,
    )
    matchday.log(
        match.draw.event.tournament_id,
        Action.MOVED,
        f"{matchday.match_title(match)} from {old.table.label} to {new.table.label}",
        actor=actor,
        match=match,
        table=new.table,
        reason=reason,
    )
    return new


def block(tournament: Tournament, table: Table, reason: str, note: str, actor) -> TableBlock:
    """Take a free table out of use. A table with a match on it is freed first (recall or move)."""
    service.lock()
    if Hold.objects.filter(table=table, active=True).exists():
        raise ApiException("table_busy", f"{table.label} has a match on it: move or recall it first.", 409)
    if TableBlock.objects.filter(table=table, ended_at__isnull=True).exists():
        raise ApiException("already_blocked", f"{table.label} is already blocked.", 409)
    blocked = TableBlock.objects.create(table=table, reason=reason, note=note, blocked_by=actor)
    shown = TableBlock.Reason(reason).label
    matchday.log(
        tournament,
        Action.TABLE_BLOCKED,
        f"{table.label}: {shown}",
        actor=actor,
        table=table,
        reason=note,
    )
    return blocked


def unblock(tournament: Tournament, table: Table, actor) -> None:
    blocked = TableBlock.objects.filter(table=table, ended_at__isnull=True).first()
    if blocked is None:
        raise ApiException("not_blocked", f"{table.label} isn't blocked.", 409)
    blocked.ended_at, blocked.ended_by = timezone.now(), actor
    blocked.save(update_fields=["ended_at", "ended_by"])
    matchday.log(tournament, Action.TABLE_UNBLOCKED, table.label, actor=actor, table=table)
    service.look_for_the_next(tournament, actor)


def tables_in_use(tournament: Tournament):
    """The tournament's tables in use: a table anywhere else is not found."""
    return (
        Table.objects.filter(venue_id=tournament.venue_id, active=True)
        if tournament.venue_id
        else Table.objects.none()
    )


def blocks_at(venue_id) -> dict:
    """The tables of a venue that are blocked now: table id -> block."""
    found = TableBlock.objects.filter(table__venue_id=venue_id, ended_at__isnull=True).select_related(
        "blocked_by"
    )
    return {block.table_id: block for block in found}


class Live:
    """What the board needs about the matches on tables, loaded once for all of them: the score sheet in
    play for each (the match's own, or the current rubber's of a tie) and the rubbers each tie has
    decided."""

    def __init__(self, reservations: list[Reservation]):
        from scoring.models import Scorecard  # scoring builds on competitions, as reservations does

        matches = [reservation.match for reservation in reservations]
        ties = [match.id for match in matches if match.draw.event.is_team]
        rubbers = Rubber.objects.filter(match_id__in=ties).order_by("position") if ties else []
        self.decided: dict = {match_id: [] for match_id in ties}
        current: dict = {}
        for rubber in rubbers:
            if rubber.status == Rubber.Status.COMPLETED:
                self.decided[rubber.match_id].append(rubber.winner_id)
            elif rubber.status == Rubber.Status.SCHEDULED and rubber.match_id not in current:
                current[rubber.match_id] = rubber
        singles = [match.id for match in matches if match.id not in self.decided]
        found = Scorecard.objects.filter(
            Q(match_id__in=singles) | Q(rubber_id__in=[rubber.id for rubber in current.values()])
        ).select_related("umpire", "rubber")
        by_match = {card.match_id: card for card in found if card.match_id}
        by_rubber = {card.rubber_id: card for card in found if card.rubber_id}
        self.sheets = {
            match.id: by_rubber.get(current[match.id].id) if match.id in current else by_match.get(match.id)
            for match in matches
        }

    def in_play(self, match: Match) -> bool:
        """Scoring has started: a point on the sheet, or for a tie an earlier rubber already decided."""
        if self.decided.get(match.id):
            return True
        sheet = self.sheets.get(match.id)
        return sheet is not None and sheet.revision > 0


def in_play(match: Match) -> bool:
    reservation = match.reservations.filter(status=Reservation.Status.ACTIVE).first()
    return reservation is not None and Live([reservation]).in_play(match)


def describe_table(reservation: Reservation, live: Live, now=None) -> dict:
    """What the board shows about the match on a table: its state, its call, its umpire and its score."""
    now = now or timezone.now()
    match = reservation.match
    event: Event = match.draw.event
    sheet = live.sheets.get(match.id)
    playing = live.in_play(match)
    reported = {side: getattr(reservation, f"{side}_reported_at") for side in SIDES}
    called_at = reservation.called_at or reservation.created_at
    grace_until = called_at + timedelta(minutes=event.call_grace_minutes)
    if playing:
        state = IN_PLAY
    elif all(reported.values()):
        state = WARMING_UP
    else:
        state = CALLED
    no_show = [side for side in SIDES if state == CALLED and reported[side] is None and now >= grace_until]
    # Calls since the first call of this stint: a move to another table calls the match there too.
    calls = [call for call in reservation.match.calls.all() if call.called_at >= called_at]
    score = None
    if sheet is not None and sheet.revision > 0:
        score = {
            "games_won": list(sheet.state.get("games_won", [0, 0])),
            "points": list(sheet.state.get("points", [0, 0])),
            "rubber": sheet.rubber.position if sheet.rubber_id else None,
        }
    if event.is_team:
        won = live.decided.get(match.id, [])
        score = {
            **(score or {"games_won": [0, 0], "points": [0, 0], "rubber": None}),
            "rubbers_won": [won.count(match.entry_a_id), won.count(match.entry_b_id)],
        }
    return {
        "state": state,
        "call": {
            "called_at": called_at,
            "calls": max(1, len(calls)),
            "last_called_at": calls[-1].called_at if calls else called_at,
            "grace_until": grace_until,
            "a_reported_at": reported["a"],
            "b_reported_at": reported["b"],
            "no_show": no_show,
        },
        "umpire": sheet.umpire.display_name if sheet is not None and sheet.umpire else "",
        "score": score,
    }


def table_state(blocked, live: dict | None, free: bool) -> str:
    """One word for the board: blocked first, then what the match on it is doing; a table another
    tournament's match holds at a shared venue counts as in play."""
    if blocked:
        return BLOCKED
    if live:
        return live["state"]
    return FREE if free else IN_PLAY


def desk(tournament: Tournament) -> list[dict]:
    """The check-in desk: every accepted entry of the tournament's events still to play, those not yet
    checked in first, then by event and name."""
    entries = (
        Entry.objects.filter(
            event__tournament=tournament,
            status=Entry.Status.ACCEPTED,
            event__status__in=[Event.Status.SCHEDULED, Event.Status.IN_PROGRESS],
        )
        .select_related("event", "checked_in_by")
        .prefetch_related("players__user")
    )
    rows = [
        {
            "id": entry.id,
            "event_id": entry.event_id,
            "event_name": entry.event.name,
            "title": service.entry_title(entry),
            "checked_in_at": entry.checked_in_at,
            "checked_in_by": entry.checked_in_by.display_name if entry.checked_in_by else "",
        }
        for entry in entries
    ]
    rows.sort(key=lambda row: (row["checked_in_at"] is not None, row["event_name"], row["title"].lower()))
    return rows


def log_of(tournament: Tournament, match_id=None, limit: int = 200) -> list[dict]:
    """The latest match-day log entries, newest first."""
    found = tournament.match_day_log.select_related("actor", "table")
    if match_id:
        found = found.filter(Q(match_id=match_id))
    return [
        {
            "id": entry.id,
            "at": entry.at,
            "action": entry.action,
            "action_label": entry.get_action_display(),
            "summary": entry.summary,
            "reason": entry.reason,
            "actor": entry.actor.display_name if entry.actor else "",
            "match_id": entry.match_id,
            "table": entry.table.label if entry.table else "",
        }
        for entry in found[:limit]
    ]
