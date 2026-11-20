"""The public events listing (REQ-042): Coast TT tournaments and external events together."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from competitions.models import Event, Tournament
from competitions.streams import domain_of
from organizations.models import Membership

from .models import ExternalEvent

LISTED = [
    Tournament.Status.PUBLISHED,
    Tournament.Status.IN_PROGRESS,
    Tournament.Status.COMPLETED,
    Tournament.Status.CANCELLED,
]


def today_in(zone: str, now: datetime | None = None) -> date:
    return (now or timezone.now()).astimezone(ZoneInfo(zone)).date()


def my_clubs(user) -> set:
    if not user.is_authenticated:
        return set()
    return set(Membership.objects.active().filter(user=user).values_list("organization_id", flat=True))


def _tournament_categories(tournament) -> list[str]:
    found = set()
    for event in tournament.events.all():
        kind = {Event.Kind.DOUBLES: "doubles", Event.Kind.JUMBLES: "doubles", Event.Kind.TEAM: "team"}
        found.add(kind.get(event.kind, "singles"))
    return sorted(found)


def tournament_item(tournament, now) -> dict:
    today = today_in(tournament.timezone, now)
    live = tournament.status == Tournament.Status.IN_PROGRESS or (
        tournament.status == Tournament.Status.PUBLISHED
        and tournament.starts_on <= today <= tournament.ends_on
    )
    return {
        "kind": "coast",
        "id": tournament.id,
        "name": tournament.name,
        "organizer": tournament.organization.name,
        "host_id": tournament.organization_id,
        "starts_on": tournament.starts_on,
        "ends_on": tournament.ends_on,
        "timezone": tournament.timezone,
        "venue": tournament.venue.name if tournament.venue else "",
        "town": tournament.venue.town if tournament.venue else tournament.organization.town,
        "categories": _tournament_categories(tournament),
        "status": "cancelled"
        if tournament.status == Tournament.Status.CANCELLED
        else ("completed" if tournament.status == Tournament.Status.COMPLETED else "scheduled"),
        "review": None,
        "live": live,
        "info_url": "",
        "info_domain": "",
        "live_url": "",
        "live_domain": "",
        "entry_info": "",
    }


def external_item(event, now) -> dict:
    today = today_in(event.timezone, now)
    on = event.status == ExternalEvent.Status.SCHEDULED and (
        event.marked_live or event.starts_on <= today <= event.ends_on
    )
    past = event.ends_on < today
    return {
        "kind": "external",
        "id": event.id,
        "name": event.name,
        "organizer": event.organizer,
        "host_id": event.submitted_by_org_id,
        "starts_on": event.starts_on,
        "ends_on": event.ends_on,
        "timezone": event.timezone,
        "venue": event.venue,
        "town": event.town,
        "categories": list(event.categories),
        "status": event.status if event.status != ExternalEvent.Status.SCHEDULED or not past else "completed",
        "review": event.review,
        "live": on,
        "info_url": event.info_url,
        "info_domain": domain_of(event.info_url) if event.info_url else "",
        "live_url": event.live_url if on else "",
        "live_domain": domain_of(event.live_url) if on and event.live_url else "",
        "entry_info": event.entry_info,
    }


def listing(user, *, when=None, start=None, end=None, town="", category="", host=None, ours=False):
    """Everything listed for `user`, soonest first (latest first for the past). Approved external events
    show to everyone; pending ones only to members of the club that submitted them."""
    now = timezone.now()
    clubs = my_clubs(user)
    tournaments = (
        Tournament.objects.filter(status__in=LISTED)
        .select_related("organization", "venue")
        .prefetch_related("events")
    )
    externals = ExternalEvent.objects.filter(
        Q(review=ExternalEvent.Review.APPROVED)
        | Q(review=ExternalEvent.Review.PENDING, submitted_by_org__in=clubs)
    )
    if start:
        tournaments = tournaments.filter(ends_on__gte=start)
        externals = externals.filter(ends_on__gte=start)
    if end:
        tournaments = tournaments.filter(starts_on__lte=end)
        externals = externals.filter(starts_on__lte=end)
    if town:
        tournaments = tournaments.filter(
            Q(venue__town__iexact=town) | Q(venue__isnull=True, organization__town__iexact=town)
        )
        externals = externals.filter(town__iexact=town)
    if host:
        tournaments = tournaments.filter(organization_id=host)
        externals = externals.filter(submitted_by_org_id=host)
    if ours:
        tournaments = tournaments.filter(organization_id__in=clubs)
        externals = externals.filter(submitted_by_org_id__in=clubs)
    items = [tournament_item(t, now) for t in tournaments] + [external_item(e, now) for e in externals]
    if category:
        items = [item for item in items if category in item["categories"]]
    if when in ("upcoming", "past"):

        def finished(item):
            return item["ends_on"] < today_in(item["timezone"], now)

        items = [item for item in items if finished(item) == (when == "past")]
    reverse = when == "past"
    return sorted(items, key=lambda item: (item["starts_on"], item["name"]), reverse=reverse)
