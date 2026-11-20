import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from organizations.models import Organization

INVITATION_TTL = timedelta(days=14)


def invitation_expiry():
    return timezone.now() + INVITATION_TTL


class Guest(models.Model):
    """A player entered by a club's staff before they have an account (REQ-003). The guest is a user
    with no way to sign in (no address of theirs, no password), so entries, matches and results refer to
    it like any player. Claiming moves everything it is part of to the claimant's account; the guest
    stays behind as a record of who it became."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="guest")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="guests")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__display_name", "created_at"]

    def __str__(self):
        return f"Guest {self.user.display_name} ({self.organization_id})"


class GuestInvitation(models.Model):
    """Staff ask the person behind a guest to claim it (REQ-003), by email, phone or both. It carries a
    single-use link (only its hash is kept): whoever opens it creates their account from the guest, or
    signs in and claims it. An account signed in with the verified email also sees it in its inbox.
    It is answered once: accepted, declined, revoked or lapsed."""

    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        DECLINED = "declined"
        REVOKED = "revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField(blank=True)  # stored lower-cased; blank for a phone-only invitation
    phone = models.CharField(max_length=16, blank=True)  # E.164, where staff will share the link
    # Null for invitations made before links existed: unique, so they can't share a blank value.
    token_hash = models.CharField(max_length=64, unique=True, null=True, editable=False)  # noqa: DJ001
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=invitation_expiry)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["guest"], condition=models.Q(status="pending"), name="one_open_guest_invitation"
            )
        ]

    def __str__(self):
        return f"{self.email or self.phone} for {self.guest_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()


class GuestClaim(models.Model):
    """An accepted invitation and what came of it. `merged`: everything moved to the claimant.
    `conflict`: something of the guest's clashes with the claimant's own records (the same event, the
    same club, the same match), nothing moved, and staff must resolve it. `rejected`: staff closed it.
    Names are never compared: only an accepted invitation joins two identities."""

    class Status(models.TextChoices):
        MERGED = "merged"
        CONFLICT = "conflict"
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="claims")
    invitation = models.OneToOneField(GuestInvitation, on_delete=models.CASCADE, related_name="claim")
    claimant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices)
    # What stopped the merge, in words, e.g. ["Entered in the same event"].
    clashes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A guest becomes one account: at most one claim stands open or merged at a time.
            models.UniqueConstraint(
                fields=["guest"],
                condition=models.Q(status__in=["merged", "conflict"]),
                name="one_live_guest_claim",
            )
        ]

    def __str__(self):
        return f"{self.guest_id} by {self.claimant_id} ({self.status})"


class GuestClaimEvent(models.Model):
    """The audit trail of a claim: who did what, when, and why."""

    class Action(models.TextChoices):
        ACCEPTED = "accepted"
        MERGED = "merged"
        CONFLICT = "conflict"
        RETRIED = "retried"
        REJECTED = "rejected"

    claim = models.ForeignKey(GuestClaim, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    note = models.CharField(max_length=500, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"{self.claim_id}: {self.action}"
