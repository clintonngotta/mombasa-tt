import uuid

from django.conf import settings
from django.db import models


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


class MembershipQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=Membership.Status.ACTIVE)

    def is_admin(self, user, organization) -> bool:
        return self.active().filter(organization=organization, user=user, role=Membership.Role.ADMIN).exists()


class Membership(models.Model):
    """A player's link to one organization. Roles are a placeholder pair until the permission
    catalog and role templates arrive (TASK-013)."""

    class Role(models.TextChoices):
        ADMIN = "admin"
        MEMBER = "member"

    class Status(models.TextChoices):
        ACTIVE = "active"
        LEFT = "left"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    joined_at = models.DateTimeField(auto_now_add=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="org_membership_unique"),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.organization_id} ({self.role})"


class JoinRequest(models.Model):
    """A player's request to join an organization (REQ-004). Staff approve or reject it."""

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

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
