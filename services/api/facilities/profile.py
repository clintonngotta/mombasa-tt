"""Facility branch profiles (REQ-044, TASK-101): who finds a branch, and whether it is open now."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from organizations.models import Membership, Organization

from .models import Venue

FACILITY_KINDS = [Organization.Kind.FACILITY, Organization.Kind.CLUB_FACILITY]


def findable(user):
    """Branches the user may find: public profiles of facility organizations, and members-only ones of
    facilities the user is an active member of. Hidden profiles and switched-off venues never show."""
    mine = Membership.objects.active().filter(user=user).values("organization")
    return Venue.objects.filter(
        Q(profile="public") | Q(profile="members", organization__in=mine),
        active=True,
        organization__kind__in=FACILITY_KINDS,
    )


def local_now(venue: Venue, now: datetime | None = None) -> datetime:
    return (now or timezone.now()).astimezone(ZoneInfo(venue.organization.timezone))


def closure_on(venue: Venue, day):
    """The closure covering `day`, from prefetched closures."""
    return next((c for c in venue.closures.all() if c.starts_on <= day <= c.ends_on), None)


def is_open(venue: Venue, now: datetime | None = None) -> bool:
    """Open at this moment, in the organization's timezone: inside one of today's blocks, and today isn't
    a closure. Expects opening_hours and closures prefetched."""
    here = local_now(venue, now)
    if closure_on(venue, here.date()) is not None:
        return False
    moment = here.time()
    return any(
        h.weekday == here.weekday() and h.opens <= moment < h.closes for h in venue.opening_hours.all()
    )


def with_profile(queryset):
    return queryset.select_related("organization").prefetch_related("opening_hours", "closures", "tables")
