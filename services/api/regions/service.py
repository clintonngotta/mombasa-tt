"""Who reaches a governing body's agenda, articles and meetings (REQ-048). A regional body works for the
clubs of its region; the national body (TASK-107) for every club of its country."""

from django.db.models import Q

from core.exceptions import ApiException
from core.permissions import is_platform_super_admin
from organizations.access import jurisdiction, official_for
from organizations.models import BODY_KINDS, Membership, Organization, PositionHolder

BODY = Organization.Kind.REGIONAL_BODY
NATIONAL = Organization.Kind.NATIONAL_BODY


def region_clubs(body: Organization):
    """The clubs and facilities a body works for: its region's, or its country's for the national body."""
    return Organization.objects.filter(jurisdiction(body)).exclude(kind__in=BODY_KINDS)


def club_reach(org: Organization) -> Q:
    """The bodies that work for a club: its region's and its country's."""
    if not org.country:
        return Q(pk__in=[])
    national = Q(kind=NATIONAL, country=org.country)
    if not org.region:
        return national
    return national | Q(kind=BODY, country=org.country, region__iexact=org.region)


def bodies_of(user):
    """Bodies whose agenda and articles reach the user: those they belong to, and those of the region
    and country of the clubs they are an active member of."""
    mine = Membership.objects.active().filter(user=user).select_related("organization")
    scope = Q(pk__in=[])
    for membership in mine:
        org = membership.organization
        if org.is_body:
            scope |= Q(pk=org.pk)
        else:
            scope |= club_reach(org)
    return Organization.objects.filter(scope, kind__in=BODY_KINDS)


def reads_body(user, body: Organization) -> bool:
    """Members of the body or of its region's clubs, the region's officials and platform super admins."""
    if is_platform_super_admin(user) or official_for(user, body):
        return True
    return (
        Membership.objects.active()
        .filter(user=user)
        .filter(Q(organization=body) | Q(organization__in=region_clubs(body)))
        .exists()
    )


def require_body(organization: Organization) -> None:
    if not organization.is_body:
        raise ApiException("not_a_regional_body", "Only a regional or national body does that.", 404)


def require_reader(user, body: Organization) -> None:
    require_body(body)
    if not reads_body(user, body):
        raise ApiException("permission_denied", "Only the region's clubs can see that.", 403)


def article_reaches(user, article) -> bool:
    """A published article reaches members of the clubs it is for, and the body's own members."""
    body = article.organization
    clubs = region_clubs(body) if article.audience == article.Audience.REGION else article.clubs.all()
    return (
        Membership.objects.active()
        .filter(user=user)
        .filter(Q(organization=body) | Q(organization__in=clubs))
        .exists()
    )


def articles_for(user, base):
    """Published articles of `base` (an Article queryset) that reach the user."""
    clubs = Membership.objects.active().filter(user=user).values("organization")
    mine = Membership.objects.active().filter(user=user).select_related("organization")
    region = Q(pk__in=[])
    for membership in mine:
        org = membership.organization
        if not org.is_body:
            region |= Q(organization__in=Organization.objects.filter(club_reach(org)))
    reach = (
        Q(organization__in=clubs) | Q(audience="chosen", clubs__in=clubs) | (Q(audience="region") & region)
    )
    return base.filter(reach, status="published").distinct()


def committee_users(organization: Organization):
    return {
        holder.membership.user
        for holder in PositionHolder.objects.filter(
            position__organization=organization,
            position__retired_at__isnull=True,
            ended_at__isnull=True,
            membership__status=Membership.Status.ACTIVE,
        ).select_related("membership__user")
    }
