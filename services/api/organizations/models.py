import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from core.timezones import DEFAULT_TIMEZONE

from .permissions import ALL_PERMISSIONS, BODY_ROLES, ROLE_TEMPLATES, Permission, RoleKey

INVITATION_TTL = timedelta(days=14)


class Organization(models.Model):
    """A club, a facility, or both (REQ-004). Its name and town are searchable by any signed-in user."""

    class Kind(models.TextChoices):
        CLUB = "club"
        FACILITY = "facility"
        CLUB_FACILITY = "club_facility"
        # The table tennis body of one catalogue region (REQ-045, REQ-048): it runs regional tournaments,
        # meetings, the yearly agenda, articles to the region's clubs and sponsorships.
        REGIONAL_BODY = "regional_body"
        # The country's table tennis body (REQ-045): one per country; its officials approve national
        # tournaments. Like a regional body it is created by a platform super admin (TASK-107).
        NATIONAL_BODY = "national_body"
        # A coach's own organizing desk (REQ-047): set up from their coach profile so they can run
        # tournaments under their own name or their firm's. Never listed in the club directory.
        COACHING = "coaching"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    town = models.CharField(max_length=80)
    country = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=100, blank=True)
    # How to find it on the ground: the closest landmark and the way from the main road or stage.
    directions = models.CharField(max_length=500, blank=True)
    # What the club is about, shown to players looking for a club before they join.
    description = models.TextField(max_length=2000, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CLUB)
    # Dates of the organization's tournaments and activities are entered and shown in this timezone.
    timezone = models.CharField(max_length=64, default=DEFAULT_TIMEZONE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "country",
                Lower("region"),
                condition=models.Q(kind="regional_body"),
                name="one_body_per_region",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="regional_body") | (~models.Q(country="") & ~models.Q(region="")),
                name="regional_body_has_region",
            ),
            models.UniqueConstraint(
                "country", condition=models.Q(kind="national_body"), name="one_body_per_country"
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="national_body") | (~models.Q(country="") & models.Q(region="")),
                name="national_body_has_country",
            ),
            models.CheckConstraint(
                condition=models.Q(latitude__isnull=True, longitude__isnull=True)
                | models.Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180),
                name="organization_coordinates_valid",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_body(self) -> bool:
        """A governing body: regional or national (REQ-045)."""
        return self.kind in BODY_KINDS

    @property
    def is_national_body(self) -> bool:
        return self.kind == self.Kind.NATIONAL_BODY

    @property
    def is_coaching(self) -> bool:
        return self.kind == self.Kind.COACHING


# Governing bodies (REQ-045): their members are officials and committee, not players.
BODY_KINDS: frozenset[str] = frozenset({Organization.Kind.REGIONAL_BODY, Organization.Kind.NATIONAL_BODY})


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


class OfficialAppointment(models.Model):
    """A platform-appointed official's geographic jurisdiction, kept read-only as history (decision D4).
    Since TASK-107 authority comes from holding `tournaments.approve` in the region's or country's body;
    migration 0015 made each appointment a membership of the matching body."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="official_appointments"
    )
    country = models.ForeignKey("core.Country", on_delete=models.PROTECT)
    region = models.ForeignKey("core.Region", on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "country", "region"],
                nulls_distinct=False,
                name="unique_official_jurisdiction",
            )
        ]

    def __str__(self):
        return f"{self.user.display_name} · {self.region or self.country}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.region_id and self.region.country_id != self.country_id:
            raise ValidationError({"region": "Choose a region of the appointed country."})


def seed_roles(organization: Organization) -> dict[str, Role]:
    """Create the template roles for a new organization, keyed by RoleKey. Only bodies get the body
    templates (Official)."""
    return {
        key: Role.objects.create(organization=organization, key=key, name=name, permissions=sorted(perms))
        for key, name, perms in ROLE_TEMPLATES
        if organization.is_body or key not in BODY_ROLES
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


class AdminHandover(models.Model):
    """Who is an organization's one admin, and how that changed (REQ-045). The admin nominates a member,
    who must accept; a platform super admin can appoint one directly with a reason. Every row is kept."""

    class Kind(models.TextChoices):
        NOMINATION = "nomination"
        APPOINTMENT = "appointment"

    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        DECLINED = "declined"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="admin_handovers")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.NOMINATION)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(status="pending"),
                name="org_one_pending_admin_handover",
            ),
        ]

    def __str__(self):
        return f"{self.organization_id}: {self.from_user_id} -> {self.to_user_id} ({self.status})"


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


class CommitteeField(models.Model):
    """A custom detail an organization keeps about its committee (REQ-045): per position (e.g. the
    portfolio it covers) or per holder (e.g. the date they were elected). Member-visible fields are shown
    to every member with the committee; staff-only ones only to holders of governance.manage. Retired,
    never deleted, so recorded values survive."""

    class AppliesTo(models.TextChoices):
        POSITION = "position"
        HOLDER = "holder"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="committee_fields")
    label = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=MemberField.Kind.choices)
    options = ArrayField(models.CharField(max_length=60), default=list, blank=True)  # CHOICE only
    required = models.BooleanField(default=False)
    visibility = models.CharField(
        max_length=10, choices=MemberField.Visibility.choices, default=MemberField.Visibility.STAFF
    )
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.POSITION)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "label"]
        constraints = [
            models.UniqueConstraint(
                Lower("label"),
                "organization",
                condition=models.Q(retired_at__isnull=True),
                name="org_committee_field_label_unique",
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.organization_id})"


class CommitteePosition(models.Model):
    """A seat on an organization's committee (REQ-045), such as chair or treasurer, held by at most one
    active member at a time. Holding it may grant a role, so the treasurer gets the finance permission
    while they hold the seat. Retired positions keep their history."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="committee_positions"
    )
    name = models.CharField(max_length=80)
    order = models.PositiveIntegerField(default=0)
    term_start = models.DateField(null=True, blank=True)
    term_end = models.DateField(null=True, blank=True)
    grants_role = models.ForeignKey(
        Role, on_delete=models.SET_NULL, null=True, blank=True, related_name="committee_positions"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "organization",
                condition=models.Q(retired_at__isnull=True),
                name="org_committee_position_name_unique",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.organization_id})"


class PositionHolder(models.Model):
    """Someone's time in a committee position. The current holder has no `ended_at`; past holders stay
    as the committee history."""

    class EndReason(models.TextChoices):
        REPLACED = "replaced"
        STEPPED_DOWN = "stepped_down"
        LEFT = "left"  # they left the organization
        POSITION_RETIRED = "position_retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    position = models.ForeignKey(CommitteePosition, on_delete=models.CASCADE, related_name="holders")
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="committee_holdings")
    started_on = models.DateField()
    ended_on = models.DateField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, choices=EndReason.choices, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["position"],
                condition=models.Q(ended_at__isnull=True),
                name="committee_position_one_holder",
            ),
        ]

    def __str__(self):
        return f"{self.membership_id} as {self.position_id}"


class CommitteeFieldValue(models.Model):
    """A value for one committee field: on a position, or on one holder's time in it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    field = models.ForeignKey(CommitteeField, on_delete=models.CASCADE, related_name="values")
    position = models.ForeignKey(
        CommitteePosition, on_delete=models.CASCADE, null=True, blank=True, related_name="field_values"
    )
    holder = models.ForeignKey(
        PositionHolder, on_delete=models.CASCADE, null=True, blank=True, related_name="field_values"
    )
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(position__isnull=False, holder__isnull=True)
                | models.Q(position__isnull=True, holder__isnull=False),
                name="committee_value_one_owner",
            ),
            models.UniqueConstraint(
                fields=["field", "position"],
                condition=models.Q(position__isnull=False),
                name="committee_value_position_unique",
            ),
            models.UniqueConstraint(
                fields=["field", "holder"],
                condition=models.Q(holder__isnull=False),
                name="committee_value_holder_unique",
            ),
        ]

    def __str__(self):
        return f"{self.field_id} for {self.position_id or self.holder_id}"
