import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.functions import Lower

from organizations.models import Organization

MAX_ACTIVE_VENUES = 20
MAX_ACTIVE_TABLES = 60
MAX_TRAINING_HOURS = 42
MAX_OPENING_HOURS = 28  # four opening blocks a day
MAX_CLOSURES = 60
MAX_AMENITIES = 20


class Venue(models.Model):
    """A place where an organization plays (REQ-007). Venues and tables are switched off, never deleted,
    so tournaments and later reservations keep pointing at the place they used."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="venues")
    name = models.CharField(max_length=120)
    town = models.CharField(max_length=80)
    address = models.CharField(max_length=200, blank=True)
    # How to find it on the ground: the closest landmark and the way from the main road or stage.
    directions = models.CharField(max_length=500, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    active = models.BooleanField(default=True)
    # A facility branch's profile (REQ-044). `town` is the city; country and region come from the
    # catalogue like an organization's.
    country = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    rules = models.TextField(max_length=2000, blank=True)
    amenities = ArrayField(models.CharField(max_length=60), default=list, blank=True)
    profile = models.CharField(
        max_length=8,
        choices=[("hidden", "Hidden"), ("members", "Members only"), ("public", "Public")],
        default="hidden",
        help_text="Who finds this branch in the facility finder: nobody, the organization's members, "
        "or every signed-in player.",
    )
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
            models.CheckConstraint(
                condition=models.Q(latitude__isnull=True, longitude__isnull=True)
                | models.Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180),
                name="venue_coordinates_valid",
            ),
        ]

    def __str__(self):
        return self.name


class Table(models.Model):
    """One physical table at a venue. It has a single identity however many events use it (REQ-014)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="tables")
    label = models.CharField(max_length=40)
    # A facility splits its tables: match tables for play and tournaments, training tables for coaching.
    kind = models.CharField(
        max_length=8, choices=[("match", "Match"), ("training", "Training")], default="match"
    )
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


class TrainingHour(models.Model):
    """A weekly time when the club trains, in the organization's timezone. Signed-in players looking for a
    club see these; training plans and sessions stay with members. Slots may overlap (juniors and seniors
    on different tables)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="training_hours")
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday
    starts = models.TimeField()
    ends = models.TimeField()
    label = models.CharField(max_length=80, blank=True)  # who it is for, e.g. "Juniors" or "Open play"
    venue = models.ForeignKey(Venue, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["weekday", "starts", "ends"]
        constraints = [
            models.CheckConstraint(condition=models.Q(weekday__lte=6), name="training_hour_weekday"),
            models.CheckConstraint(
                condition=models.Q(ends__gt=models.F("starts")), name="training_hour_ends_after_start"
            ),
        ]

    def __str__(self):
        return f"{self.organization_id} {self.weekday} {self.starts}-{self.ends}"


class OpeningHour(models.Model):
    """When a venue is open on one weekday, in its organization's timezone (REQ-044, shared with REQ-021).
    A day may have several blocks (a lunch break), and a day with none is closed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="opening_hours")
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday
    opens = models.TimeField()
    closes = models.TimeField()

    class Meta:
        ordering = ["weekday", "opens"]
        constraints = [
            models.CheckConstraint(condition=models.Q(weekday__lte=6), name="opening_hour_weekday"),
            models.CheckConstraint(
                condition=models.Q(closes__gt=models.F("opens")), name="opening_hour_closes_after_opening"
            ),
        ]

    def __str__(self):
        return f"{self.venue_id} {self.weekday} {self.opens}-{self.closes}"


class Closure(models.Model):
    """Days a venue stays shut whatever its weekly hours say: a holiday, repairs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="closures")
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["starts_on"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="closure_ends_after_start"
            ),
        ]

    def __str__(self):
        return f"{self.venue_id} closed {self.starts_on}-{self.ends_on}"
