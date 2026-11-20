"""Table bookings at a venue (REQ-021, TASK-036)."""

from django.db import transaction
from django.utils import timezone

from core.exceptions import ApiException
from training.club_sessions import _as_json, table_clashes

from .models import Booking, Table
from .profile import closure_on, local_now


def within_hours(venue, starts, ends) -> bool:
    """The whole slot falls inside one of the day's opening blocks, on a day the venue isn't closed."""
    first, last = local_now(venue, starts), local_now(venue, ends)
    if first.date() != last.date() or closure_on(venue, first.date()) is not None:
        return False
    return any(
        h.weekday == first.weekday() and h.opens <= first.time() and last.time() <= h.closes
        for h in venue.opening_hours.all()
    )


def check_request(venue, tables, starts, ends) -> None:
    if ends <= timezone.now():
        raise ApiException("booking_in_past", "Choose a time that hasn't passed.", 400)
    if any(t.venue_id != venue.pk or not t.active for t in tables):
        raise ApiException("bad_tables", "Choose tables in use at this venue.", 400)
    if not within_hours(venue, starts, ends):
        raise ApiException("venue_closed", "The venue isn't open for all of that time.", 409)


@transaction.atomic
def approve(booking: Booking, actor, fee_minor=None) -> Booking:
    """Take the tables: lock them, then refuse if a tournament, training or another approved booking
    holds any of them then. Approving twice changes nothing."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status == Booking.Status.APPROVED:
        return booking
    if booking.status != Booking.Status.REQUESTED:
        raise ApiException("booking_closed", "This booking was already decided.", 409)
    tables = list(booking.tables.all())
    list(Table.objects.select_for_update().filter(pk__in=[t.pk for t in tables]).order_by("pk"))
    clashes = table_clashes(tables, booking.starts_at, booking.ends_at, exclude_booking=booking)
    if clashes:
        raise ApiException(
            "table_unavailable", "A table is taken at that time.", 409, extra={"conflicts": _as_json(clashes)}
        )
    booking.status = Booking.Status.APPROVED
    booking.fee_minor = fee_minor
    booking.decided_by = actor
    booking.decided_at = timezone.now()
    booking.save()
    _tell(booking)
    return booking


@transaction.atomic
def reject(booking: Booking, actor, reason: str) -> Booking:
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status != Booking.Status.REQUESTED:
        raise ApiException("booking_closed", "This booking was already decided.", 409)
    booking.status = Booking.Status.REJECTED
    booking.reason = reason
    booking.decided_by = actor
    booking.decided_at = timezone.now()
    booking.save()
    _tell(booking)
    return booking


@transaction.atomic
def cancel(booking: Booking, actor, reason: str = "") -> Booking:
    """A requested or approved booking that hasn't ended can be cancelled; its tables are free again.
    One that has ended stays as it was, in the history."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status not in (Booking.Status.REQUESTED, Booking.Status.APPROVED):
        raise ApiException("booking_closed", "This booking can't be cancelled now.", 409)
    if booking.ends_at <= timezone.now():
        raise ApiException("booking_over", "A booking that has ended stays in the history.", 409)
    booking.status = Booking.Status.CANCELLED
    booking.reason = reason
    booking.cancelled_by = actor
    booking.save()
    if actor.pk != booking.requester_id:
        _tell(booking)
    return booking


def _tell(booking: Booking) -> None:
    from notifications import triggers

    triggers.booking_news(booking)
