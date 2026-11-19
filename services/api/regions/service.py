"""Who reaches a regional body's agenda, articles and meetings (REQ-048)."""

from django.db.models import Q

from core.exceptions import ApiException
from core.permissions import is_platform_super_admin
from organizations.access import official_for
from organizations.models import Membership, Organization, PositionHolder

BODY = Organization.Kind.REGIONAL_BODY


def region_clubs(body: Organization):
    """The clubs and facilities of the body's region."""
    return Organization.objects.filter(country=body.country, region__iexact=body.region).exclude(kind=BODY)


def bodies_of(user):
    """Bodies whose agenda and articles reach the user: those they belong to, and those of the regions
    of the clubs they are an active member of."""
    mine = Membership.objects.active().filter(user=user).select_related("organization")
    scope = Q(pk__in=[])
    for membership in mine:
        org = membership.organization
        if org.kind == BODY:
            scope |= Q(pk=org.pk)
        elif org.country and org.region:
            scope |= Q(country=org.country, region__iexact=org.region)
    return Organization.objects.filter(scope, kind=BODY)


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
    if organization.kind != BODY:
        raise ApiException("not_a_regional_body", "Only a regional body does that.", 404)


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
        if org.kind != BODY and org.country and org.region:
            region |= Q(organization__country=org.country, organization__region__iexact=org.region)
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
