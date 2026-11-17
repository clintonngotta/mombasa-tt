import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .permissions import ALL_PERMISSIONS, ROLE_TEMPLATES, Permission, RoleKey

INVITATION_TTL = timedelta(days=14)


class Organization(models.Model):
    """A club, a facility, or both (REQ-004). Its name and town are searchable by any signed-in user."""

    class Kind(models.TextChoices):
        CLUB = "club"
        FACILITY = "facility"
        CLUB_FACILITY = "club_facility"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    town = models.CharField(max_length=80)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CLUB)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.Model):
    """A named permission bundle within one organization (REQ-005). Every organization starts with the
    template roles in ROLE_TEMPLATES and may add custom ones. Admin always holds every permission and the
    Member role applies to every active member, so neither can be deleted or assigned by hand."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="roles")
    key = models.CharField(max_length=20, choices=RoleKey.choices, blank=True, default="")
    name = models.CharField(max_length=60)
    permissions = ArrayField(
        models.CharField(max_length=40, choices=Permission.choices), default=list, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), "organization", name="org_role_name_unique"),
            models.UniqueConstraint(
                fields=["organization", "key"], condition=~models.Q(key=""), name="org_role_key_unique"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.organization_id})"

    @property
    def is_admin(self) -> bool:
        return self.key == RoleKey.ADMIN

    @property
    def is_member(self) -> bool:
        return self.key == RoleKey.MEMBER

    @property
    def permission_set(self) -> frozenset[str]:
        return ALL_PERMISSIONS if self.is_admin else frozenset(self.permissions)


def seed_roles(organization: Organization) -> dict[str, Role]:
    """Create the template roles for a new organization, keyed by RoleKey."""
    return {
        key: Role.objects.create(organization=organization, key=key, name=name, permissions=sorted(perms))
        for key, name, perms in ROLE_TEMPLATES
    }


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=Membership.Status.ACTIVE)

    def admins(self, organization):
        # A deactivated account can't act, so it doesn't count as the organization's admin.
        return self.active().filter(organization=organization, roles__key=RoleKey.ADMIN, user__is_active=True)


class Membership(models.Model):
    """A player's link to one organization. Roles (REQ-005) are assigned here; the organization's Member
    role is implicit for every active membership and is never stored in `roles`."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        LEFT = "left"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    roles = models.ManyToManyField(Role, related_name="memberships", blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    joined_at = models.DateTimeField(auto_now_add=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="org_membership_unique"),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.organization_id} ({self.status})"


class JoinRequest(models.Model):
    """A player's request to join an organization (REQ-004). Staff approve or reject it."""

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"  # settled without a staff decision, e.g. the player accepted an invitation

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="join_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="join_requests")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # A rejected player may ask again, but only one request can be open at a time.
            models.UniqueConstraint(
                fields=["organization", "user"],
                condition=models.Q(status="pending"),  # JoinRequest.Status.PENDING (not in scope in Meta)
                name="org_one_pending_join_request",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} -> {self.organization_id} ({self.status})"


def invitation_expiry():
    return timezone.now() + INVITATION_TTL


class Invitation(models.Model):
    """Staff invite someone by email to join an organization (REQ-004). The invitee sees it once they
    are signed in with that verified address, and must explicitly accept; nothing is joined until then."""

    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        DECLINED = "declined"
        REVOKED = "revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()  # stored lower-cased
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=invitation_expiry)
    decided_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(status="pending"),  # Invitation.Status.PENDING (not in scope in Meta)
                name="org_one_pending_invitation",
            ),
        ]

    def __str__(self):
        return f"{self.email} -> {self.organization_id} ({self.status})"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()  # the pending-unique constraint relies on this
        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()


class MemberField(models.Model):
    """A custom detail an organization keeps about its members (REQ-005), e.g. a membership number or
    shirt size. Member-visible fields are shown to, and filled in by, the member they describe; staff-only
    fields exist only for members holding members.manage. Fields are retired, never deleted, so the values
    recorded under them survive."""

    class Kind(models.TextChoices):
        TEXT = "text"
        NUMBER = "number"
        DATE = "date"
        BOOLEAN = "boolean"
        CHOICE = "choice"

    class Visibility(models.TextChoices):
        MEMBER = "member"
        STAFF = "staff"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="member_fields")
    label = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    options = ArrayField(models.CharField(max_length=60), default=list, blank=True)  # CHOICE only
    required = models.BooleanField(default=False)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.STAFF)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "label"]
        constraints = [
            # A retired field keeps its label; a new field may reuse it.
            models.UniqueConstraint(
                Lower("label"),
                "organization",
                condition=models.Q(retired_at__isnull=True),
                name="org_member_field_label_unique",
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.organization_id})"


class MemberFieldValue(models.Model):
    """One member's value for one custom field. `value` holds a string (text, choice, ISO date), a number
    or a boolean; an unanswered field has no row."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="field_values")
    field = models.ForeignKey(MemberField, on_delete=models.CASCADE, related_name="values")
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "field"], name="member_field_value_unique"),
        ]

    def __str__(self):
        return f"{self.field_id} for {self.membership_id}"
