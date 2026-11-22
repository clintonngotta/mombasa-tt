"""Sending a match to a table and holding what it needs (REQ-014).

Everything here runs in the caller's transaction. Whatever writes or relies on holds first takes one
lock, the same for every table and person, so two requests are decided one after the other and can
never deadlock, however many tables and people each touches and in whatever order it comes to them (a
result frees some players and may hold others, in other tournaments, in the same transaction). A lock
per table and person would allow more at once, but a club sends out a few matches a minute. `dispatch`
then looks again at everything (the match, the table, each player), whatever a screen showed a moment
ago, and only then writes the holds. The partial unique indexes on `Hold` are the last line: even code
that forgot the lock could not hold a table or a person twice.

Staff may set aside the check-in and rest checks with a reason. Nothing sets aside exclusivity.
"""

import hashlib
import logging
from datetime import timedelta

from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from competitions import jumbles
from competitions.models import DrawVersion, Entry, Event, Match, Rubber, Tournament
from core.exceptions import ApiException
from facilities.models import Table

from .models import Hold, MatchCall, Reservation, TableBlock

logger = logging.getLogger(__name__)

CHECK_IN, REST = "check_in", "rest"
OVERRIDABLE = (CHECK_IN, REST)
# Which check a refusal belongs to, when it is one staff may set aside.
SETS_ASIDE = {"not_checked_in": CHECK_IN, "resting": REST}


class Blocked(ApiException):
    """Why a match can't go to a table right now: a code and a sentence that names the real constraint."""

    def __init__(self, code: str, message: str):
        super().__init__(code, message, 409)
        self.blocker = code
        self.message = message
        self.until = None  # for a rest: when it is over


_GATE = int.from_bytes(hashlib.sha256(b"coast-tt:reservations").digest()[:8], "big", signed=True)


def lock() -> None:
    """Wait for the one lock over all tables and people; it is let go when the transaction ends."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_GATE])


def players_of_match(match: Match) -> list:
    """The people who play it: both entries of a singles or doubles match. For a tie, see rubbers."""
    return [
        place.user
        for entry in (match.entry_a, match.entry_b)
        if entry is not None
        for place in entry.players.all()  # callers listing many matches prefetch players and users
    ]


def current_rubber(match: Match) -> Rubber | None:
    return match.rubbers.filter(status=Rubber.Status.SCHEDULED).order_by("position").first()


def people_to_hold(match: Match) -> tuple[list, Rubber | None]:
    """Who is held while the match is on the table: its players, or for a tie the players of the rubber
    whose turn it is (REQ-011: not every team member for the whole tie)."""
    if not match.draw.event.is_team:
        return players_of_match(match), None
    rubber = current_rubber(match)
    if rubber is None:
        return [], None
    return [placed.user for placed in rubber.players.select_related("user")], rubber


def _name(user) -> str:
    return user.display_name


def ensure_dispatchable(match: Match) -> None:
    """The match itself is ready: published draw, event under way, undecided, both sides known (which
    is what its official predecessors having finished means) and, for a tie, lineups in."""
    event = match.draw.event
    if match.draw.status != DrawVersion.Status.PUBLISHED:
        raise Blocked("draw_not_published", "Only matches of the published draw are played.")
    if event.tournament.status != Tournament.Status.IN_PROGRESS or event.status != Event.Status.IN_PROGRESS:
        raise Blocked("not_in_play", "Start the tournament and the event before sending matches to tables.")
    if match.status != Match.Status.SCHEDULED:
        raise Blocked("match_decided", "This match is already decided.")
    if event.paused_at is not None:
        raise Blocked(
            "event_paused",
            "This event is paused: a corrected result changed who plays a match that had started. "
            "Settle it under Corrections first.",
        )
    if match.entry_a_id is None or match.entry_b_id is None:
        raise Blocked(
            "waiting_for_players", "An earlier match hasn't finished, so both sides aren't known yet."
        )
    if event.is_team and not match.rubbers.exists():
        raise Blocked(
            "waiting_for_lineups", "Both teams hand in their lineups before the tie goes to a table."
        )


def is_dispatchable(match: Match) -> bool:
    try:
        ensure_dispatchable(match)
    except Blocked:
        return False
    return True


def rest_until(user, event: Event):
    """When the player's rest after the last match they played is over, by this event's rest period.
    A walkover, a rubber that wasn't needed or a match called back is not play; nor is a disqualification
    before any game, though one part-way through is."""
    at_the_table = [Match.Outcome.PLAYED, Match.Outcome.RETIRED]
    dq = Match.Outcome.DISQUALIFIED
    played = (
        Q(rubber__isnull=True, reservation__ending=Reservation.Ending.DECIDED)
        & (
            Q(reservation__match__outcome__in=at_the_table)
            | (Q(reservation__match__outcome=dq) & ~Q(reservation__match__games=[]))
        )
    ) | (
        Q(rubber__status=Rubber.Status.COMPLETED)
        & (Q(rubber__outcome__in=at_the_table) | (Q(rubber__outcome=dq) & ~Q(rubber__games=[])))
    )
    last = (
        Hold.objects.filter(played, user=user, active=False)
        .order_by("-released_at")
        .values_list("released_at", flat=True)
        .first()
    )
    return last + timedelta(minutes=event.rest_minutes) if last else None


def dispatch(
    match: Match,
    table: Table,
    actor,
    *,
    overrides=(),
    reason: str = "",
    automatic: bool = False,
    carry: Reservation | None = None,
) -> Reservation:
    """Send the match to the table: hold the table and the players, or say what stands in the way.
    `carry` is the reservation of the table a match is moved from: its first call and who had reported
    stay with the match. Call inside a transaction, with the tournament row locked."""
    overrides = [name for name in OVERRIDABLE if name in overrides]
    if overrides and not reason:
        raise ApiException("reason_required", "Say why the check is set aside.", 400)
    ensure_dispatchable(match)
    lock()

    # Everything below is looked at after the lock: nothing a screen showed earlier is trusted.
    match = Match.objects.select_related("draw__event__tournament", "entry_a", "entry_b").get(pk=match.pk)
    ensure_dispatchable(match)
    people, rubber = people_to_hold(match)
    event = match.draw.event
    if match.reservations.filter(status=Reservation.Status.ACTIVE).exists():
        raise Blocked("already_on_table", "This match is already on a table.")
    table = Table.objects.select_related("venue").get(pk=table.pk)
    if not table.active or table.venue_id != event.tournament.venue_id:
        raise Blocked("table_unavailable", "That table isn't one of this tournament's tables in use.")
    held = (
        Hold.objects.filter(table=table, active=True)
        .select_related("reservation__match__draw__event")
        .first()
    )
    if held:
        raise Blocked(
            "table_busy", f"{table.label} is taken by a match of {held.reservation.match.draw.event.name}."
        )
    blocked = TableBlock.objects.filter(table=table, ended_at__isnull=True).first()
    if blocked:
        raise Blocked("table_blocked", f"{table.label} is blocked: {blocked.get_reason_display().lower()}.")
    for blocked in standing_in_the_way(match, people, rubber):
        if SETS_ASIDE.get(blocked.blocker) not in overrides:
            raise blocked

    try:
        with transaction.atomic():
            now = timezone.now()
            reservation = Reservation.objects.create(
                match=match,
                table=table,
                created_by=actor,
                automatic=automatic,
                overrides=overrides,
                override_reason=reason,
                called_at=(carry.called_at or carry.created_at) if carry else now,
                a_reported_at=carry.a_reported_at if carry else None,
                b_reported_at=carry.b_reported_at if carry else None,
            )
            MatchCall.objects.create(match=match, reservation=reservation, called_by=actor)
            Hold.objects.create(reservation=reservation, table=table)
            Hold.objects.bulk_create(
                Hold(reservation=reservation, user=user, rubber=rubber) for user in people
            )
    except IntegrityError as error:  # something held them without the lock: the indexes still refuse
        raise Blocked("resource_busy", "The table or one of the players was taken a moment ago.") from error
    match.table = table
    match.dispatched_at = reservation.created_at
    match.save(update_fields=["table", "dispatched_at"])
    from . import umpires

    umpires.take_table_umpire(match, rubber, table, actor)
    from notifications import triggers

    triggers.called_to_table(match, reservation, [user.pk for user in people])
    if carry is None:  # a move is logged by `control.move`, with its reason
        from competitions import matchday

        how = "automatically " if automatic else ""
        matchday.log(
            event.tournament_id,
            matchday.Action.CALLED,
            f"{matchday.match_title(match)} sent {how}to {table.label}",
            actor=actor,
            match=match,
            table=table,
            reason=reason,
        )
    if not automatic:  # automatic dispatch announces once it has sent everything it can
        from . import board

        board.announce_up_next(event.tournament)
    return reservation


def standing_in_the_way(match: Match, people: list, rubber: Rubber | None) -> list[Blocked]:
    """Everything about the people of a match that stops it going to any table right now, in the order
    dispatch refuses them. The ready queue shows the same list, so what it says is what would happen."""
    event = match.draw.event
    found = []
    if event.is_team:
        # A tie holds its players rubber by rubber, but a team still plays one tie at a time.
        sides = [match.entry_a_id, match.entry_b_id]
        elsewhere = (
            Reservation.objects.filter(status=Reservation.Status.ACTIVE)
            .filter(Q(match__entry_a__in=sides) | Q(match__entry_b__in=sides))
            .exclude(match=match)
            .select_related("table", "match__entry_a", "match__entry_b")
        )
        for held in elsewhere:
            for entry in (held.match.entry_a, held.match.entry_b):
                if entry.id in sides:
                    found.append(
                        Blocked("team_busy", f"{entry_title(entry)} is playing a tie on {held.table.label}.")
                    )
    busy = Hold.objects.filter(user__in=people, active=True).select_related("user", "reservation__table")
    for hold in busy:
        found.append(
            Blocked("player_busy", f"{_name(hold.user)} is playing on {hold.reservation.table.label}.")
        )
    umpiring = _umpiring_now(people)
    if umpiring:
        found.append(
            Blocked("player_umpiring", f"{_name(umpiring[0])} is umpiring a match on {umpiring[1]}.")
        )
    umpire = _umpire_of(match, rubber)
    if umpire is not None and Hold.objects.filter(user=umpire, active=True).exists():
        found.append(Blocked("umpire_busy", f"The umpire, {_name(umpire)}, is playing a match right now."))
    absent = [e for e in (match.entry_a, match.entry_b) if not jumbles.checked_in(e)]
    if absent:
        names = " and ".join(entry_title(entry) for entry in absent)
        verb = "hasn't" if len(absent) == 1 else "haven't"
        found.append(Blocked("not_checked_in", f"{names} {verb} checked in."))
    now = timezone.now()
    for user in people:
        until = rest_until(user, event)
        if until and until > now:
            minutes = max(1, round((until - now).total_seconds() / 60))
            blocked = Blocked(
                "resting",
                f"{_name(user)} finished a match less than {event.rest_minutes} minutes ago: "
                f"{minutes} more to rest.",
            )
            blocked.until = until
            found.append(blocked)
    return found


def entry_title(entry: Entry) -> str:
    return entry.team_name or " / ".join(place.user.display_name for place in entry.players.all())


def _umpire_of(match: Match, rubber: Rubber | None):
    """Whoever is assigned to score the match (or the rubber whose turn it is), if anybody."""
    from scoring.models import Scorecard  # scoring builds on competitions, as this app does

    target = {"rubber": rubber} if rubber else {"match": match}
    card = Scorecard.objects.filter(**target).select_related("umpire").first()
    return card.umpire if card else None


def _umpiring_now(people: list):
    """One of these people is the umpire of a match that is on a table, or of the rubber now being
    played in a tie that is: (person, table label)."""
    from scoring.models import Scorecard

    cards = list(
        Scorecard.objects.filter(umpire__in=people, confirmed_at__isnull=True).select_related(
            "umpire", "match", "rubber__match"
        )
    )
    on_tables = {
        held.match_id: held
        for held in Reservation.objects.filter(
            match__in=[card.tie_or_match for card in cards], status=Reservation.Status.ACTIVE
        ).select_related("table", "match")
    }
    for card in cards:
        held = on_tables.get(card.tie_or_match.id)
        if held is None:
            continue
        if card.rubber_id is None or current_rubber(held.match) == card.rubber:
            return card.umpire, held.table.label
    return None


def ensure_umpire_free(match: Match, umpire) -> None:
    """Somebody playing right now isn't made the umpire of a match that is already on a table."""
    lock()
    on_table = match.reservations.filter(status=Reservation.Status.ACTIVE).exists()
    if on_table and Hold.objects.filter(user=umpire, active=True).exists():
        raise Blocked("umpire_busy", f"{_name(umpire)} is playing a match right now.")


def release(reservation: Reservation, actor, ending: str, reason: str = "") -> None:
    """Free the table and the players. For a decided match this runs in the transaction of the result."""
    if reservation.status != Reservation.Status.ACTIVE:
        return
    now = timezone.now()
    freed = list(reservation.holds.filter(active=True, user__isnull=False).values_list("user_id", flat=True))
    reservation.holds.filter(active=True).update(active=False, released_at=now)
    reservation.status = Reservation.Status.RELEASED
    reservation.ending = ending
    reservation.released_at = now
    reservation.released_by = actor
    reservation.release_reason = reason
    reservation.save(update_fields=["status", "ending", "released_at", "released_by", "release_reason"])
    _hold_those_waiting_for(freed)


def recall(match: Match, actor, reason: str) -> None:
    """Staff take the match off its table. Its score sheet, if any, is untouched."""
    reservation = match.reservations.filter(status=Reservation.Status.ACTIVE).first()
    if reservation is None:
        raise Blocked("not_on_table", "This match isn't on a table.")
    lock()
    players = list(reservation.holds.filter(user__isnull=False).values_list("user_id", flat=True))
    release(reservation, actor, Reservation.Ending.RECALLED, reason)
    from notifications import triggers

    triggers.taken_off_table(match, players, reason)
    from competitions import matchday

    matchday.log(
        match.draw.event.tournament_id,
        matchday.Action.RECALLED,
        f"{matchday.match_title(match)} off {reservation.table.label}",
        actor=actor,
        match=match,
        table=reservation.table,
        reason=reason,
    )
    off_the_table(match)
    look_for_the_next(match.draw.event.tournament, actor)


def look_for_the_next(tournament: Tournament, actor=None) -> None:
    """A table or a player has just become free: automatic dispatch, if it is on, looks at once."""
    from . import board  # the board is built on this module

    try:
        with transaction.atomic():
            board.run_auto(tournament, actor)
        board.announce_up_next(tournament)
    except Exception:
        # Sending the next match out is a convenience. Whatever goes wrong with it, the result or the
        # recall that freed the table stands; a person can still send the match from the board.
        logger.exception("Automatic dispatch failed for tournament %s", tournament.id)


def off_the_table(match: Match) -> None:
    match.table = None
    match.dispatched_at = None
    match.save(update_fields=["table", "dispatched_at"])


def on_match_decided(sender, match: Match, **kwargs) -> None:
    for reservation in match.reservations.filter(status=Reservation.Status.ACTIVE):
        lock()
        release(reservation, None, Reservation.Ending.DECIDED)
    # A result frees a table and may make the next match ready.
    look_for_the_next(match.draw.event.tournament)


def on_event_closed(sender, event: Event, actor=None, **kwargs) -> None:
    """The event was completed or cancelled: whatever it still had on a table comes off, so nothing it
    held stays blocked for the other tournaments at the venue."""
    left = Reservation.objects.filter(match__draw__event=event, status=Reservation.Status.ACTIVE)
    for reservation in left.select_related("match"):
        lock()
        release(reservation, actor, Reservation.Ending.CLOSED)
        off_the_table(reservation.match)
    look_for_the_next(event.tournament, actor)


def on_rubber_decided(sender, rubber: Rubber, tie_decided: bool = False, **kwargs) -> None:
    """The rubber's players are free (their rest starts now); the next rubber's players are held, if
    the tie goes on and they are free. If one of them is busy elsewhere the hold is simply not there
    yet: `missing_people` says so, and they are held the moment whatever holds them lets go."""
    reservation = rubber.match.reservations.filter(status=Reservation.Status.ACTIVE).first()
    if reservation is None:
        return
    lock()
    done = reservation.holds.filter(rubber=rubber, active=True)
    freed = list(done.values_list("user_id", flat=True))
    done.update(active=False, released_at=timezone.now())
    if not tie_decided:  # what is left of a decided tie isn't played: nobody is held for it
        hold_next_rubber(reservation)
        following = current_rubber(reservation.match)
        if following is not None:
            from . import umpires

            umpires.take_table_umpire(reservation.match, following, reservation.table, None)
    _hold_those_waiting_for(freed)


def hold_next_rubber(reservation: Reservation) -> list:
    """Hold the players of the tie's current rubber if they aren't held yet. Returns those who could
    not be held because they are in use elsewhere. Call with the lock taken."""
    match = reservation.match
    if match.status != Match.Status.SCHEDULED or reservation.status != Reservation.Status.ACTIVE:
        return []
    rubber = current_rubber(match)
    if rubber is None:
        return []
    people = [placed.user for placed in rubber.players.select_related("user")]
    mine = set(reservation.holds.filter(active=True, rubber=rubber).values_list("user_id", flat=True))
    missing = []
    for user in people:
        if user.id in mine:
            continue
        if Hold.objects.filter(user=user, active=True).exists():
            missing.append(user)
            continue
        Hold.objects.create(reservation=reservation, user=user, rubber=rubber)
    return missing


def missing_people(reservation: Reservation) -> list:
    """Players of the tie's current rubber who aren't held with it, because they are in use elsewhere."""
    match = reservation.match
    rubber = current_rubber(match) if match.draw.event.is_team else None
    if rubber is None or match.status != Match.Status.SCHEDULED:
        return []
    mine = set(reservation.holds.filter(active=True, rubber=rubber).values_list("user_id", flat=True))
    return [placed.user for placed in rubber.players.select_related("user") if placed.user_id not in mine]


def _hold_those_waiting_for(user_ids: list) -> None:
    """People have just become free: a tie on a table whose current rubber was waiting for one of them
    gets its hold now."""
    if not user_ids:
        return
    waiting = Reservation.objects.filter(
        status=Reservation.Status.ACTIVE,
        match__rubbers__status=Rubber.Status.SCHEDULED,
        match__rubbers__players__user__in=user_ids,
    ).distinct()
    for reservation in waiting:
        hold_next_rubber(reservation)


def active_for(tournament: Tournament) -> list[Reservation]:
    return list(
        Reservation.objects.filter(
            match__draw__event__tournament=tournament, status=Reservation.Status.ACTIVE
        )
        .select_related("table", "match__draw__event", "match__entry_a", "match__entry_b", "created_by")
        .prefetch_related(
            "holds__user", "match__calls", "match__entry_a__players__user", "match__entry_b__players__user"
        )
        .order_by("table__position", "created_at")
    )


def describe(reservation: Reservation) -> dict:
    """A reservation as ReservationSerializer shows it."""
    match = reservation.match
    return {
        "id": reservation.id,
        "table_id": reservation.table_id,
        "table": reservation.table.label,
        "event_id": match.draw.event_id,
        "event_name": match.draw.event.name,
        "match_id": match.id,
        "a": entry_title(match.entry_a),
        "b": entry_title(match.entry_b),
        "since": reservation.created_at,
        "automatic": reservation.automatic,
        "people": sorted(
            hold.user.display_name for hold in reservation.holds.all() if hold.user_id and hold.active
        ),
        "overrides": reservation.overrides,
        "override_reason": reservation.override_reason,
    }


def tables_of(tournament: Tournament) -> list[dict]:
    """The tournament's tables in use and what holds each, as TableStateSerializer shows them."""
    if tournament.venue_id is None:
        return []
    held = {
        hold.table_id: hold.reservation
        for hold in Hold.objects.filter(table__venue_id=tournament.venue_id, active=True).select_related(
            "reservation__match__draw__event__tournament"
        )
    }
    rows = []
    for table in Table.objects.filter(venue_id=tournament.venue_id, active=True):
        reservation = held.get(table.id)
        event = reservation.match.draw.event if reservation else None
        rows.append(
            {
                "id": table.id,
                "label": table.label,
                "free": reservation is None,
                # A table can be shared by tournaments at one venue: name whose match it is.
                "held_by": f"{event.tournament.name}: {event.name}" if event else "",
                "since": reservation.created_at if reservation else None,
            }
        )
    return rows
