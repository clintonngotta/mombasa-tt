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


def position_roles(membership: Membership) -> list[Role]:
    """Roles granted by the committee positions the membership currently holds (REQ-045). Admin is never
    granted this way: the organization has one admin, changed only by handover."""
    return list(
        Role.objects.filter(
            organization=membership.organization_id,
            committee_positions__retired_at__isnull=True,
            committee_positions__holders__membership=membership,
            committee_positions__holders__ended_at__isnull=True,
        )
        .exclude(key=RoleKey.ADMIN)
        .distinct()
    )


def membership_permissions(membership: Membership) -> frozenset[str]:
    """Effective permissions of an active membership: its roles, the roles its committee positions grant,
    and the organization's Member role. Uses prefetched `roles` and `organization.roles` when present."""
    if membership.status != Membership.Status.ACTIVE:
        return frozenset()
    member_role = [role for role in membership.organization.roles.all() if role.is_member]
    return roles_permissions([*membership.roles.all(), *member_role, *position_roles(membership)])


# What a country or regional official holds in a club of their jurisdiction by appointment alone: no club
# permission. They read the club as a member does (`require_membership`), approve and publish its regional
# or national tournaments (competitions.lifecycle.can_approve) and see its ranking; members, roles,
# finances and running its competitions stay with the club (user decision, 2026-11-19).
OVERSIGHT: frozenset[str] = frozenset()


def effective_permissions(user, organization: Organization) -> frozenset[str]:
    """The user's permissions here: everything for a platform super admin, otherwise what their own
    active membership grants. An official's appointment adds nothing (see OVERSIGHT)."""
    if is_platform_super_admin(user):
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
    """403 unless the user is an active member here, a platform super admin, or an official whose
    jurisdiction covers it (they read what members read). Returns the membership."""
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
