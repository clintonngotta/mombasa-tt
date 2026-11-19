"""Equipment, drills and personal training plans (REQ-026, REQ-027; TASK-042, TASK-043)."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Equipment(models.Model):
    """What a player plays with, in their own words (REQ-026). Optional and private to them; it makes no
    claim about how well they play."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="equipment"
    )
    blade = models.CharField(max_length=100, blank=True)
    forehand = models.CharField(max_length=100, blank=True)
    backhand = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Equipment of {self.user_id}"


class Drill(models.Model):
    """An exercise in a library (REQ-026): a player's own, private to them, or a club's, which its members
    see and its training staff (training.manage) edit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="drills"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="drills"
    )
    title = models.CharField(max_length=80)
    instructions = models.TextField()
    focus = models.CharField(max_length=80, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    repetitions = models.PositiveSmallIntegerField(null=True, blank=True)
    equipment = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(owner__isnull=False, organization__isnull=True)
                | Q(owner__isnull=True, organization__isnull=False),
                name="drill_one_library",
            ),
        ]

    def __str__(self):
        return self.title


class TrainingPlan(models.Model):
    """A player's own plan (REQ-027): checklist items to tick off and sessions in their calendar."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="training_plans"
    )
    title = models.CharField(max_length=80)
    goal = models.CharField(max_length=280, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class PlanItem(models.Model):
    """One step of a plan. A checklist item is just ticked off and reserves nothing. A session is a
    commitment in the player's calendar: it may not overlap their other sessions or scheduled matches."""

    class Kind(models.TextChoices):
        CHECKLIST = "checklist"
        SESSION = "session"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=120)
    notes = models.CharField(max_length=500, blank=True)
    drill = models.ForeignKey(Drill, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    order = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="checklist", starts_at__isnull=True, ends_at__isnull=True)
                | Q(kind="session", starts_at__isnull=False, ends_at__gt=F("starts_at")),
                name="plan_item_times_match_kind",
            ),
        ]

    def __str__(self):
        return self.title
