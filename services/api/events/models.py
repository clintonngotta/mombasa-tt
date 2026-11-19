"""External events in the public events listing (REQ-042, TASK-080).

An external event is a listing only: it never gains draws, entries, results or ratings in Coast TT. Club
staff submit it; a platform curator reviews it before it shows publicly. Links are https only.
"""

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q

CATEGORIES = [
    ("singles", "Singles"),
    ("doubles", "Doubles"),
    ("team", "Team"),
    ("juniors", "Juniors"),
    ("veterans", "Veterans"),
    ("women", "Women"),
    ("open", "Open"),
    ("para", "Para"),
]


class ExternalEvent(models.Model):
    class Review(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        POSTPONED = "postponed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submitted_by_org = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="external_events"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    name = models.CharField(max_length=120)
    organizer = models.CharField(max_length=120)
    starts_on = models.DateField()
    ends_on = models.DateField()
    timezone = models.CharField(max_length=64, default="Africa/Nairobi")
    venue = models.CharField(max_length=120, blank=True)
    town = models.CharField(max_length=80)
    country = models.CharField(max_length=2, default="KE")
    categories = ArrayField(models.CharField(max_length=10, choices=CATEGORIES), default=list, blank=True)
    entry_info = models.TextField(max_length=1000, blank=True)
    info_url = models.URLField(max_length=500, blank=True)
    live_url = models.URLField(max_length=500, blank=True)
    # The organizer or a curator says it's on now, whatever the dates say.
    marked_live = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    review = models.CharField(max_length=10, choices=Review.choices, default=Review.PENDING)
    review_note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_on", "name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="external_event_ends_after_start"
            ),
        ]

    def __str__(self):
        return self.name


class LinkReport(models.Model):
    """A viewer says an external event's live link is wrong. One per person; curators see them."""

    class Reason(models.TextChoices):
        BROKEN = "broken", "Doesn't work"
        WRONG = "wrong", "Wrong event"
        INAPPROPRIATE = "inappropriate", "Inappropriate"
        OTHER = "other", "Other"

    event = models.ForeignKey(ExternalEvent, on_delete=models.CASCADE, related_name="link_reports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=14, choices=Reason.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="one_link_report_per_person")]

    def __str__(self):
        return f"{self.reason} on {self.event_id}"
