import uuid

from django.db import models
from django.utils import timezone


class Job(models.Model):
    """Work that follows from a change and is written in the same transaction as the change, so it is
    never lost and never done for a change that was rolled back (REQ-015). A worker does it afterwards.
    `key` names the piece of work: writing the same key twice is one job."""

    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"
        FAILED = "failed"  # gave up after MAX_ATTEMPTS; `last_error` says why

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=60)
    key = models.CharField(max_length=200, unique=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)  # not tried before this
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["status", "available_at"], name="outbox_due")]

    def __str__(self):
        return f"{self.kind} {self.key} ({self.status})"
