"""Club penalties for absences (REQ-054).

Governance staff set one rule for each kind of absence: an accepted tournament entry that wasn't checked
in, a squad place the player didn't take up, and a training session accepted and missed. The app proposes
a penalty for each absence it finds; staff issue or waive it with a reason. The member sees their own
penalties and may appeal each once. Meetings have their own rules (REQ-046).
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Absence(models.TextChoices):
    TOURNAMENT = "tournament", "Tournament entry not attended"
    SQUAD = "squad", "Squad place not attended"
    TRAINING = "training", "Training session missed"


class PenaltyKind(models.TextChoices):
    WARNING = "warning", "Warning"
    SUSPENSION = "suspension", "Suspension from selection"
    POINTS = "points", "Penalty points"


class AbsenceRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="absence_rules"
    )
    applies_to = models.CharField(max_length=10, choices=Absence.choices)
    kind = models.CharField(max_length=10, choices=PenaltyKind.choices, default=PenaltyKind.WARNING)
    # For a suspension: how many of the organization's next squads the member is left out of.
    suspension_events = models.PositiveSmallIntegerField(null=True, blank=True)
    points = models.PositiveSmallIntegerField(null=True, blank=True)
    # An optional fine, charged through the ledger when the penalty is issued.
    fine_minor = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    # An apology sent in time means no penalty is proposed (training only: REQ-052).
    apology_excuses = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["applies_to"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "applies_to"], name="one_absence_rule_each"),
            models.CheckConstraint(
                condition=~Q(kind="suspension") | Q(suspension_events__gte=1),
                name="suspension_rule_has_events",
            ),
            models.CheckConstraint(
                condition=~Q(kind="points") | Q(points__gte=1), name="points_rule_has_points"
            ),
        ]

    def __str__(self):
        return f"{self.applies_to} rule of {self.organization_id}"


class AbsencePenalty(models.Model):
    """One absence and what it costs. It copies the rule as it stood, so changing the rule later doesn't
    change penalties already proposed."""

    class Status(models.TextChoices):
        PROPOSED = "proposed"  # found by the app; staff haven't decided
        ISSUED = "issued"
        WAIVED = "waived"

    class Appeal(models.TextChoices):
        NONE = ""
        PENDING = "pending"
        UPHELD = "upheld"  # the appeal succeeded: the penalty is waived
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="absence_penalties"
    )
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="absence_penalties"
    )
    applies_to = models.CharField(max_length=10, choices=Absence.choices)
    # What was missed: the entry, squad place or session invitation, with a title and date to show.
    source_id = models.UUIDField()
    what = models.CharField(max_length=160)
    happened_on = models.DateField()
    kind = models.CharField(max_length=10, choices=PenaltyKind.choices)
    suspension_events = models.PositiveSmallIntegerField(null=True, blank=True)
    points = models.PositiveSmallIntegerField(null=True, blank=True)
    fine_minor = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PROPOSED)
    reason = models.CharField(max_length=300, blank=True)  # why it was issued or waived
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    charge = models.OneToOneField(
        "finance.Charge", on_delete=models.SET_NULL, null=True, blank=True, related_name="absence_penalty"
    )
    appeal = models.CharField(max_length=8, choices=Appeal.choices, default="", blank=True)
    appeal_text = models.CharField(max_length=1000, blank=True)
    appealed_at = models.DateTimeField(null=True, blank=True)
    appeal_note = models.CharField(max_length=300, blank=True)
    appeal_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-happened_on", "id"]
        indexes = [
            models.Index(fields=["organization", "status"], name="absence_penalty_org_status"),
            models.Index(fields=["member", "status"], name="absence_penalty_member"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "applies_to", "source_id", "member"], name="one_penalty_per_absence"
            ),
            models.CheckConstraint(
                condition=Q(status="proposed") | Q(decided_at__isnull=False), name="decided_penalty_has_time"
            ),
            models.CheckConstraint(
                condition=~Q(status="waived") | ~Q(reason=""), name="waived_penalty_has_reason"
            ),
        ]

    def __str__(self):
        return f"{self.applies_to} penalty for {self.member_id}"
