"""Club training sessions (REQ-027, TASK-044).

Staff schedule a session on the club's tables and invite members. The tables are taken when the session
is saved: no other club session may use them at the same time, nor may a tournament at their venue (on its
planned sessions when it has a day schedule, otherwise on every day it runs). An invitation reserves nothing
in the member's calendar. Accepting does, through the same calendar check as personal training sessions
and coaching bookings, with the member's row and the session locked, so two acceptances racing each other
(or racing a booking) can't both take the same hour or the last place. Accepting twice is harmless.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from competitions.models import ScheduleSession, Tournament
from core.exceptions import ApiException
from facilities.models import Booking, Table

from .models import ClubSession, SessionInvitation
from .service import ensure_free, lock_player

RUNNING = [Tournament.Status.PUBLISHED, Tournament.Status.IN_PROGRESS]


def _aware(day, at: time, zone: str) -> datetime:
    return datetime.combine(day, at, tzinfo=ZoneInfo(zone))


def _booking_clashes(bookings, ids) -> list[dict]:
    return [
        {
            "kind": "booking",
            "title": f"Booked by {booking.requester.display_name}",
            "starts_at": booking.starts_at,
            "ends_at": booking.ends_at,
            "tables": sorted(t.label for t in booking.tables.all() if t.pk in ids),
        }
        for booking in bookings.select_related("requester").prefetch_related("tables")
    ]


def table_clashes(
    tables, starts: datetime, ends: datetime, exclude: ClubSession | None = None, exclude_booking=None
) -> list[dict]:
    """What else uses any of `tables` between `starts` and `ends`."""
    ids = [t.pk for t in tables]
    found = []
    sessions = (
        ClubSession.objects.filter(
            tables__in=ids, status=ClubSession.Status.SCHEDULED, starts_at__lt=ends, ends_at__gt=starts
        )
        .distinct()
        .prefetch_related("tables")
    )
    if exclude is not None:
        sessions = sessions.exclude(pk=exclude.pk)
    for session in sessions:
        found.append(
            {
                "kind": "club_session",
                "title": session.title,
                "starts_at": session.starts_at,
                "ends_at": session.ends_at,
                "tables": sorted(t.label for t in session.tables.all() if t.pk in ids),
            }
        )

    bookings = Booking.objects.filter(
        tables__in=ids, status=Booking.Status.APPROVED, starts_at__lt=ends, ends_at__gt=starts
    ).distinct()
    if exclude_booking is not None:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    found += _booking_clashes(bookings, ids)

    venues = {t.venue_id for t in tables}
    for tournament in Tournament.objects.filter(venue__in=venues, status__in=RUNNING):
        zone = tournament.timezone
        first, last = starts.astimezone(ZoneInfo(zone)).date(), ends.astimezone(ZoneInfo(zone)).date()
        if tournament.ends_on < first or tournament.starts_on > last:
            continue
        planned = ScheduleSession.objects.filter(tournament=tournament).prefetch_related("tables")
        if planned.exists():
            for block in planned.filter(day__gte=first, day__lte=last, tables__in=ids).distinct():
                block_starts, block_ends = (
                    _aware(block.day, block.starts, zone),
                    _aware(block.day, block.ends, zone),
                )
                if block_starts < ends and block_ends > starts:
                    found.append(
                        {
                            "kind": "tournament",
                            "title": tournament.name,
                            "starts_at": block_starts,
                            "ends_at": block_ends,
                            "tables": sorted(t.label for t in block.tables.all() if t.pk in ids),
                        }
                    )
        else:
            # No day schedule yet: the tournament may use any of the venue's tables on any of its days.
            day_starts = _aware(max(first, tournament.starts_on), time.min, zone)
            day_ends = _aware(min(last, tournament.ends_on) + timedelta(days=1), time.min, zone)
            found.append(
                {
                    "kind": "tournament",
                    "title": tournament.name,
                    "starts_at": day_starts,
                    "ends_at": day_ends,
                    "tables": sorted(t.label for t in tables if t.venue_id == tournament.venue_id),
                }
            )
    return sorted(found, key=lambda c: c["starts_at"])


def _as_json(clashes: list[dict]) -> list[dict]:
    return [
        {**c, "starts_at": c["starts_at"].isoformat(), "ends_at": c["ends_at"].isoformat()} for c in clashes
    ]


def ensure_tables_free(tables, starts, ends, exclude: ClubSession | None = None) -> None:
    """409 with what is in the way when a table is taken. Locks the tables first, so two sessions saved
    at the same moment queue up and the second sees the first."""
    list(Table.objects.select_for_update().filter(pk__in=[t.pk for t in tables]).order_by("pk"))
    clashes = table_clashes(tables, starts, ends, exclude)
    if clashes:
        raise ApiException(
            "table_unavailable",
            "A table you chose is in use at that time.",
            409,
            extra={"conflicts": _as_json(clashes)},
        )


def accepted_count(session: ClubSession) -> int:
    return session.invitations.filter(status=SessionInvitation.Status.ACCEPTED).count()


@transaction.atomic
def accept(invitation: SessionInvitation) -> SessionInvitation:
    user = invitation.user
    lock_player(user)
    session = ClubSession.objects.select_for_update().get(pk=invitation.session_id)
    invitation = SessionInvitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.status == SessionInvitation.Status.ACCEPTED:
        return invitation  # already accepted: nothing more to do
    if session.status != ClubSession.Status.SCHEDULED:
        raise ApiException("session_cancelled", "This session was cancelled.", 409)
    if session.ends_at <= timezone.now():
        raise ApiException("session_over", "This session is over.", 409)
    if session.capacity is not None and accepted_count(session) >= session.capacity:
        raise ApiException("session_full", "This session is full.", 409)
    ensure_free(
        user,
        session.starts_at,
        session.ends_at,
        message="You already have something on at that time.",
    )
    invitation.status = SessionInvitation.Status.ACCEPTED
    invitation.responded_at = timezone.now()
    invitation.save(update_fields=["status", "responded_at"])
    return invitation


@transaction.atomic
def decline(invitation: SessionInvitation) -> SessionInvitation:
    invitation = SessionInvitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.status != SessionInvitation.Status.DECLINED:
        invitation.status = SessionInvitation.Status.DECLINED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=["status", "responded_at"])
    return invitation


def record_attendance(
    invitation: SessionInvitation, attended: bool | None, actor, *, late: bool = False
) -> SessionInvitation:
    """Staff mark a member by hand (also over a check-in the member made). The record says it was staff."""
    session = invitation.session
    if session.status != ClubSession.Status.SCHEDULED:
        raise ApiException("session_cancelled", "This session was cancelled.", 409)
    if attended is not None and session.starts_at > timezone.now():
        raise ApiException("session_not_started", "Attendance is recorded once the session starts.", 409)
    late = bool(late and attended)
    by_staff = invitation.attendance_source == SessionInvitation.Source.STAFF
    if invitation.attended != attended or invitation.late != late or (attended is not None and not by_staff):
        invitation.attended = attended
        invitation.late = late
        invitation.attendance_by = actor if attended is not None else None
        invitation.attendance_at = timezone.now() if attended is not None else None
        invitation.attendance_source = SessionInvitation.Source.STAFF if attended is not None else ""
        invitation.check_in_distance_m = invitation.check_in_accuracy_m = None
        invitation.save(
            update_fields=[
                "attended",
                "late",
                "attendance_by",
                "attendance_at",
                "attendance_source",
                "check_in_distance_m",
                "check_in_accuracy_m",
            ]
        )
    return invitation


def ensure_no_training_on(tables, starts, ends) -> None:
    """For a tournament's day session (REQ-044): refuse tables a club or facility training session
    already holds then, with what is in the way. The tables are locked first, as for training."""
    ids = [t.pk for t in tables]
    list(Table.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    sessions = (
        ClubSession.objects.filter(
            tables__in=ids, status=ClubSession.Status.SCHEDULED, starts_at__lt=ends, ends_at__gt=starts
        )
        .distinct()
        .prefetch_related("tables")
    )
    clashes = [
        {
            "kind": "club_session",
            "title": session.title,
            "starts_at": session.starts_at,
            "ends_at": session.ends_at,
            "tables": sorted(t.label for t in session.tables.all() if t.pk in ids),
        }
        for session in sessions
    ]
    approved = Booking.objects.filter(
        tables__in=ids, status=Booking.Status.APPROVED, starts_at__lt=ends, ends_at__gt=starts
    ).distinct()
    clashes += _booking_clashes(approved, ids)
    if clashes:
        raise ApiException(
            "table_unavailable",
            "Training or a booking holds a table you chose at that time.",
            409,
            extra={"conflicts": _as_json(clashes)},
        )
