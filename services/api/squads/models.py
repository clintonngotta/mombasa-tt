"""Representative squads (REQ-050): the players a club, or a regional body for its region, sends to a
tournament that isn't run on Coast TT.

A squad has slots (men's team of 4, women's singles of 2). Competition staff pick players into slots; each
player accepts or declines, and staff replace whoever declines. Picking outside the rotation the app
recommends takes a reason, which is kept.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Squad(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"  # staff are still choosing; nobody has been told
        PUBLISHED = "published"  # the players picked are told and answer

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="squads"
    )
    title = models.CharField(max_length=120)  # the tournament, as staff name it
    # The listed external event it is for (REQ-042), when there is one.
    external_event = models.ForeignKey(
        "events.ExternalEvent", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    # Which rating orders the recommendation.
    discipline = models.CharField(max_length=10, default="singles")
    notes = models.CharField(max_length=1000, blank=True)
    # In order: [{"id": str, "label": str, "places": int}].
    slots = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_on", "id"]
        indexes = [models.Index(fields=["organization", "starts_on"], name="squad_org_start")]
        constraints = [
            models.CheckConstraint(condition=Q(ends_on__gte=F("starts_on")), name="squad_dates_in_order"),
        ]

    def __str__(self):
        return self.title


class SquadPlace(models.Model):
    """One player picked into one slot of a squad, and their answer."""

    class Status(models.TextChoices):
        PICKED = "picked"  # chosen, hasn't answered
        ACCEPTED = "accepted"
        DECLINED = "declined"
        REMOVED = "removed"  # taken out by staff

    OPEN = (Status.PICKED, Status.ACCEPTED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    squad = models.ForeignKey(Squad, on_delete=models.CASCADE, related_name="places")
    slot = models.CharField(max_length=12)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="squad_places")
    # For a regional body's squad: the club the player comes from.
    club = models.ForeignKey(
        "organizations.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PICKED)
    # Whether the app's rotation recommended them for this place, and if not, why staff chose them.
    recommended = models.BooleanField(default=True)
    override_reason = models.CharField(max_length=300, blank=True)
    picked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    picked_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["picked_at", "id"]
        indexes = [models.Index(fields=["user", "status"], name="squad_place_user_status")]
        constraints = [
            models.UniqueConstraint(
                fields=["squad", "user"],
                condition=Q(status__in=["picked", "accepted"]),
                name="one_open_place_per_squad",
            ),
            models.CheckConstraint(
                condition=Q(recommended=True) | ~Q(override_reason=""), name="squad_override_has_reason"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.squad_id} ({self.status})"
