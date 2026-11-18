"""Entering an event (REQ-008): who may enter whom, capacity, the waiting list, withdrawal and check-in.

Every function here runs with the tournament row locked (`select_for_update`), like every other change
to a tournament, so two requests for the last place are decided one after the other and the number of
accepted entries can never pass the event's capacity. The database also refuses a player in two standing
entries of one event (`one_live_entry_per_event`).
"""

from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.exceptions import ApiException

from .models import MAX_TEAM_ROSTER, MIN_TEAM_ROSTER, Entry, EntryPlayer, Event, Tournament

S = Entry.Status


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def ensure_taking_entries(tournament: Tournament, event: Event) -> None:
    """Entries change only while the tournament is public and the event hasn't started."""
    if tournament.status == Tournament.Status.DRAFT:
        raise _conflict("not_published", "Publish the tournament before taking entries.")
    if tournament.is_closed or event.status != Event.Status.SCHEDULED:
        raise _conflict(
            "entries_closed",
            f"This event is {event.get_status_display().lower()}, so its entries can't change.",
        )


def ensure_registration_open(event: Event) -> None:
    now = timezone.now()
    if event.registration_opens_at and now < event.registration_opens_at:
        raise _conflict("registration_not_open", "Registration for this event hasn't opened yet.")
    if event.registration_closes_at and now >= event.registration_closes_at:
        raise _conflict("registration_closed", "Registration for this event has closed.")


def has_room(event: Event) -> bool:
    return event.capacity is None or event.entries.filter(status=S.ACCEPTED).count() < event.capacity


def ensure_room(event: Event) -> None:
    if not has_room(event):
        raise _conflict(
            "event_full",
            f"All {event.capacity} places are taken. Put the entry on the waiting list instead.",
        )


def roster_problem(event: Event, players: list, team_name: str, captain) -> dict[str, str]:
    """Field errors for an entry's shape: one player, two distinct players, or a named team with a
    captain from its roster."""
    count = len(players)
    if event.kind == Event.Kind.SINGLES and count != 1:
        return {"player_ids": "A singles entry is one player."}
    if event.kind == Event.Kind.DOUBLES and count != 2:
        return {"player_ids": "A doubles entry is two different players."}
    if event.kind == Event.Kind.TEAM:
        if not team_name:
            return {"team_name": "Give the team a name."}
        if not MIN_TEAM_ROSTER <= count <= MAX_TEAM_ROSTER:
            return {"player_ids": f"A team has {MIN_TEAM_ROSTER} to {MAX_TEAM_ROSTER} players."}
        if captain is None or captain not in players:
            return {"captain_id": "The captain is one of the team's players."}
    return {}


def _already_entered(taken, actor, by_staff: bool) -> ApiException:
    """Staff are told who; a player learns only about themselves, since other people's pending and
    waitlisted entries are not theirs to see."""
    if by_staff:
        names = ", ".join(sorted({place.user.display_name for place in taken}))
        return _conflict("already_entered", f"Already entered in this event: {names}.")
    if any(place.user_id == actor.id for place in taken):
        return _conflict("already_entered", "You are already entered in this event.")
    return _conflict("already_entered", "One of these players is already entered in this event.")


def create(event: Event, actor, players: list, *, team_name: str, captain, by_staff: bool) -> Entry:
    """Open admission and staff entries take a place or join the waitlist. Closed self-entry is pending."""
    is_team = event.kind == Event.Kind.TEAM
    taken = EntryPlayer.objects.filter(event=event, live=True, user__in=players).select_related("user")
    if taken:
        raise _already_entered(taken, actor, by_staff)
    if is_team and event.entries.filter(status__in=Entry.LIVE, team_name__iexact=team_name).exists():
        raise _conflict("team_name_taken", "Another team in this event has that name.")
    status = S.PENDING
    if by_staff or event.admission == Event.Admission.OPEN:
        status = S.ACCEPTED if has_room(event) else S.WAITLISTED
    try:
        with transaction.atomic():
            entry = Entry.objects.create(
                event=event,
                status=status,
                team_name=team_name if is_team else "",
                captain=captain if is_team else None,
                entered_by=actor,
                decided_at=timezone.now() if status != S.PENDING else None,
                decided_by=actor if by_staff else None,
            )
            EntryPlayer.objects.bulk_create(
                EntryPlayer(entry=entry, event=event, user=player, position=position)
                for position, player in enumerate(players)
            )
    except IntegrityError as error:  # lost a race the check above couldn't see
        raise _conflict(
            "already_entered", "One of these players is already entered in this event."
        ) from error
    return entry


def _require(entry: Entry, *allowed: str, doing: str) -> None:
    if entry.status not in allowed:
        raise _conflict(
            "invalid_transition", f"An entry that is {entry.get_status_display().lower()} can't be {doing}."
        )


def _decide(entry: Entry, actor, status: str, reason: str = "") -> None:
    entry.status = status
    entry.decided_at = timezone.now()
    entry.decided_by = actor
    entry.reason = reason
    entry.save(update_fields=["status", "decided_at", "decided_by", "reason"])


def _stand_down(entry: Entry) -> None:
    """The entry no longer stands: its players are free to enter again and it is no longer checked in."""
    entry.players.update(live=False)
    undo_check_in(entry)


def accept(entry: Entry, actor) -> str:
    """Give the entry one of the event's places, from pending or from the waiting list. Capacity is
    checked again here every time. Returns the news to send its players."""
    _require(entry, S.PENDING, S.WAITLISTED, doing="accepted")
    ensure_room(entry.event)
    news = "promoted" if entry.status == S.WAITLISTED else "accepted"
    _decide(entry, actor, S.ACCEPTED)
    return news


def waitlist(entry: Entry, actor) -> None:
    _require(entry, S.PENDING, doing="put on the waiting list")
    _decide(entry, actor, S.WAITLISTED)


def reject(entry: Entry, actor, reason: str) -> None:
    _require(entry, S.PENDING, S.WAITLISTED, doing="rejected")
    _decide(entry, actor, S.REJECTED, reason)
    _stand_down(entry)


def withdraw(entry: Entry, actor, reason: str = "") -> None:
    """By one of its players, or by staff on their behalf. The place it held is free again; nobody is
    promoted into it automatically."""
    _require(entry, *Entry.LIVE, doing="withdrawn")
    entry.withdrawn_at = timezone.now()
    entry.save(update_fields=["withdrawn_at"])
    _decide(entry, actor, S.WITHDRAWN, reason)  # records who withdrew it, player or staff
    _stand_down(entry)


def check_in(entry: Entry, actor) -> None:
    """Arrived at the venue. Says nothing about the fee, and needs nothing about it either."""
    if entry.status != S.ACCEPTED:
        raise _conflict("not_accepted", "Only an accepted entry can be checked in.")
    if entry.checked_in_at is None:
        entry.checked_in_at = timezone.now()
        entry.checked_in_by = actor
        entry.save(update_fields=["checked_in_at", "checked_in_by"])
        entry.players.filter(checked_in_at__isnull=True).update(checked_in_at=entry.checked_in_at)


def self_check_in(entry: Entry, actor, tournament: Tournament) -> None:
    if entry.status != S.ACCEPTED:
        raise _conflict("not_accepted", "Only an accepted entry can be checked in.")
    now = timezone.now()
    day = now.astimezone(ZoneInfo(tournament.timezone)).date()
    if not tournament.starts_on <= day <= tournament.ends_on:
        raise _conflict("check_in_not_today", "Self check-in is available on the tournament days.")
    if entry.checked_in_at is not None:
        return
    entry.players.filter(user=actor, checked_in_at__isnull=True).update(checked_in_at=now)
    if not entry.players.filter(checked_in_at__isnull=True).exists():
        entry.checked_in_at = now
        entry.checked_in_by = actor
        entry.save(update_fields=["checked_in_at", "checked_in_by"])


def undo_check_in(entry: Entry) -> None:
    entry.checked_in_at = None
    entry.checked_in_by = None
    entry.save(update_fields=["checked_in_at", "checked_in_by"])
    entry.players.filter(checked_in_at__isnull=False).update(checked_in_at=None)
