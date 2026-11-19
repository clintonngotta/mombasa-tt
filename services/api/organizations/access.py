"""Permission checks and grant rules for one organization (REQ-005).

Call the checks inside the transaction that does the work. Anything that changes who holds which role
(assigning roles, editing or deleting a role, removing or losing a member) first locks the organization
row with `lock_organization`, so concurrent changes run one after another: two admins removing each other
at the same moment can never leave the organization without an admin.
"""

from collections.abc import Iterable

from django.db.models import Q

from core.exceptions import ApiException
from core.permissions import is_platform_super_admin

from .models import Membership, OfficialAppointment, Organization, Role
from .permissions import ALL_PERMISSIONS, RoleKey


def membership_permissions(membership: Membership) -> frozenset[str]:
    """Effective permissions of an active membership: its roles plus the organization's Member role.
    Uses prefetched `roles` and `organization.roles` when present."""
    if membership.status != Membership.Status.ACTIVE:
        return frozenset()
    member_role = [role for role in membership.organization.roles.all() if role.is_member]
    return roles_permissions([*membership.roles.all(), *member_role])


def effective_permissions(user, organization: Organization) -> frozenset[str]:
    if is_platform_super_admin(user) or official_for(user, organization):
        return ALL_PERMISSIONS
    membership = (
        Membership.objects.active()
        .filter(organization=organization, user=user)
        .select_related("organization")
        .prefetch_related("roles", "organization__roles")
        .first()
    )
    return membership_permissions(membership) if membership else frozenset()


def require_membership(user, organization: Organization) -> Membership | None:
    """403 unless the user is an active member here. Returns the membership."""
    if is_platform_super_admin(user) or official_for(user, organization):
        return None
    membership = Membership.objects.active().filter(organization=organization, user=user).first()
    if membership is None:
        raise ApiException("permission_denied", "Only members of this organization can see that.", 403)
    return membership


def official_for(user, organization: Organization, *, country_only=False) -> bool:
    if not user.is_authenticated or not user.is_active or not organization.country:
        return False
    matches = OfficialAppointment.objects.filter(user=user, country_id=organization.country)
    scope = Q(region__isnull=True)
    if organization.region and not country_only:
        scope |= Q(region__country_id=organization.country, region__name__iexact=organization.region)
    return matches.filter(scope).exists()


def managed_organizations(user):
    if is_platform_super_admin(user):
        return Organization.objects.all()
    scope = Q(pk__in=[])
    for appointed in OfficialAppointment.objects.filter(user=user).select_related("region"):
        if appointed.region and appointed.region.country_id == appointed.country_id:
            scope |= Q(country=appointed.country_id, region__iexact=appointed.region.name)
        elif appointed.region_id is None:
            scope |= Q(country=appointed.country_id)
    return Organization.objects.filter(scope)


def require_permission(user, organization: Organization, *any_of: str) -> frozenset[str]:
    """403 unless the user holds at least one of `any_of` here. Returns their effective permissions."""
    granted = effective_permissions(user, organization)
    if not granted.intersection(any_of):
        raise ApiException("permission_denied", "Your role in this organization doesn't allow that.", 403)
    return granted


def require_within_authority(granted: frozenset[str], permissions: Iterable[str]) -> None:
    """Nobody can grant, revoke or wield through others a permission they don't hold themselves."""
    beyond = set(permissions) - granted
    if beyond:
        raise ApiException(
            "beyond_your_authority",
            "You can only grant or remove permissions you hold yourself.",
            403,
        )


def lock_organization(organization: Organization) -> Organization:
    return Organization.objects.select_for_update().get(pk=organization.pk)


def ensure_admin_remains(organization: Organization, losing: Membership) -> None:
    """409 if `losing` is the organization's only active admin. Requires `lock_organization` first."""
    others = Membership.objects.admins(organization).exclude(pk=losing.pk)
    if losing.roles.filter(key=RoleKey.ADMIN).exists() and not others.exists():
        raise ApiException(
            "last_admin",
            "An organization needs its admin. Nominate a successor, who accepts, before leaving.",
            409,
        )


def roles_permissions(roles: Iterable[Role]) -> frozenset[str]:
    granted: set[str] = set()
    for role in roles:
        granted |= role.permission_set
    return frozenset(granted)
