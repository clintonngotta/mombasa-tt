"""The notification inbox (REQ-019, TASK-033).

The inbox is durable: an alert is a row, written in the same transaction as what it tells of. Each alert
names its subject (what it is about) and the version of that subject it describes, so the same event
sent ten times is one alert, and when the subject changes the older alerts about it are marked
superseded: opening one shows where things stand now, through its link. Push (TASK-034) is a best-effort
copy of these rows and never the only record.
"""

import uuid

from django.conf import settings
from django.db import models


class Category(models.TextChoices):
    UP_NEXT = "up_next", "Up next"
    TABLE_CALL = "table_call", "Called to table"
    ASSIGNMENT = "assignment", "Changed or cancelled assignment"
    REGISTRATION = "registration", "Registration decisions"
    ANNOUNCEMENT = "announcement", "Announcements and awards"
    TRAINING = "training", "Training sessions"
    ACTIVITY = "activity", "Club activities"
    SODA = "soda", "Soda games"
    BOOKING = "booking", "Bookings"
    DUES = "dues", "Dues and payments"
    EVENTS = "events", "Events listing"


# What a player can't switch off: being called to a table is how match day works.
ALWAYS_ON = {Category.TABLE_CALL}


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    category = models.CharField(max_length=14, choices=Category.choices)
    title = models.CharField(max_length=140)
    body = models.CharField(max_length=500, blank=True)
    # Where to go: an app path that shows the subject as it is now.
    link = models.CharField(max_length=300, blank=True)
    # What it is about ("match:<id>", "activity:<id>") and which version of it this alert describes.
    subject = models.CharField(max_length=80)
    version = models.CharField(max_length=80, default="1")
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # A newer alert about the same subject replaced this one.
    superseded = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["recipient", "subject"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "category", "subject", "version"], name="one_alert_per_subject_version"
            )
        ]

    def __str__(self):
        return f"{self.category} for {self.recipient_id}: {self.title}"


class Preference(models.Model):
    """A category a player switched off. Absent means on."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_off"
    )
    category = models.CharField(max_length=14, choices=Category.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "category"], name="one_preference_per_category")
        ]

    def __str__(self):
        return f"{self.user_id} off {self.category}"
