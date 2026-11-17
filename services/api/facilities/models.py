import uuid

from django.db import models
from django.db.models.functions import Lower

from organizations.models import Organization

MAX_ACTIVE_VENUES = 20
MAX_ACTIVE_TABLES = 60


class Venue(models.Model):
    """A place where an organization plays (REQ-007). Venues and tables are switched off, never deleted,
    so tournaments and later reservations keep pointing at the place they used."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="venues")
    name = models.CharField(max_length=120)
    town = models.CharField(max_length=80)
    address = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "organization",
                condition=models.Q(active=True),
                name="venue_active_name_unique",
            ),
        ]

    def __str__(self):
        return self.name


class Table(models.Model):
    """One physical table at a venue. It has a single identity however many events use it (REQ-014)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="tables")
    label = models.CharField(max_length=40)
    position = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("label"), "venue", condition=models.Q(active=True), name="table_active_label_unique"
            ),
        ]

    def __str__(self):
        return f"{self.label} ({self.venue_id})"
