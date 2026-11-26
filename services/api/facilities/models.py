import uuid

from django.conf import settings
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
        # Finding branches near a point narrows on these first (core.nearby).
        indexes = [models.Index(fields=["latitude", "longitude"], name="venue_position")]

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


class Pass(models.Model):
    """What a visitor can pay for at a branch (REQ-044): a day pass (the entry fee) or a longer pass,
    with what it includes. Amounts are integer minor units with their currency, as the facility set them.
    A price that has been sold is switched off, never deleted, so its visits keep pointing at it."""

    class Kind(models.TextChoices):
        DAY = "day", "Day pass"
        WEEK = "week", "Week pass"
        MONTH = "month", "Month pass"
        SESSIONS = "sessions", "Sessions bundle"

    DAYS = {"day": 1, "week": 7, "month": 30}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="passes")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="KES")
    # A sessions bundle: how many visits it covers, and how many days it stays valid.
    sessions = models.PositiveSmallIntegerField(null=True, blank=True)
    valid_days = models.PositiveSmallIntegerField(null=True, blank=True)
    benefits = ArrayField(models.CharField(max_length=80), default=list, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["amount_minor", "name"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(kind="sessions") | models.Q(sessions__gte=1, valid_days__gte=1),
                name="pass_bundle_has_sessions_and_days",
            ),
        ]

    def __str__(self):
        return f"{self.name} {self.amount_minor} {self.currency}"

    @property
    def days(self) -> int:
        return self.valid_days if self.kind == self.Kind.SESSIONS else self.DAYS[self.kind]


class Visit(models.Model):
    """A visit recorded at the door: who came (a Coast TT player, or a walk-in's name kept only for the
    facility), the pass sold, what was collected and how. Recording collection is not payment
    processing. A visit is never edited or deleted: a mistake is reversed with a reason and the original
    stays (REQ-022)."""

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MPESA = "mpesa", "M-Pesa"
        OTHER = "other", "Other"
        PASS = "pass", "Covered by a pass"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="visits")
    pass_sold = models.ForeignKey(Pass, on_delete=models.PROTECT, related_name="visits")
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="facility_visits",
    )
    walk_in_name = models.CharField(max_length=80, blank=True)
    # A visit on a pass the player already holds: the visit that sold it. Nothing is collected.
    covered_by = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="uses"
    )
    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    method = models.CharField(max_length=5, choices=Method.choices)
    reference = models.CharField(max_length=60, blank=True)
    # The facility's local day of the visit, and the last day the pass sold covers.
    visited_on = models.DateField()
    valid_until = models.DateField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reversal_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        indexes = [
            models.Index(fields=["venue", "visited_on"]),
            models.Index(fields=["player", "-visited_on"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(player__isnull=False, walk_in_name="")
                | models.Q(player__isnull=True) & ~models.Q(walk_in_name=""),
                name="visit_is_a_player_or_a_walk_in",
            ),
            models.CheckConstraint(
                condition=models.Q(method__in=["cash", "pass"]) | ~models.Q(reference=""),
                name="visit_external_payment_has_reference",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gte=models.F("visited_on")), name="visit_valid_after_visit"
            ),
            models.CheckConstraint(
                condition=models.Q(method="pass", covered_by__isnull=False, amount_minor=0)
                | (~models.Q(method="pass") & models.Q(covered_by__isnull=True)),
                name="visit_on_a_pass_collects_nothing",
            ),
        ]

    def __str__(self):
        return f"{self.venue_id} {self.visited_on} {self.amount_minor} {self.currency}"


class Booking(models.Model):
    """A request to use tables at a venue for a time (REQ-021). A request holds nothing; approval takes
    the tables, checked against tournaments, training and other bookings in one locked transaction.
    Cancelling frees them; a booking that has ended stays in the history. Fees are recorded by staff,
    never charged online."""

    class Status(models.TextChoices):
        REQUESTED = "requested"
        APPROVED = "approved"
        REJECTED = "rejected"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name="bookings")
    tables = models.ManyToManyField(Table, related_name="bookings")
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="table_bookings"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    # What staff said it costs, if anything; recorded, not collected.
    fee_minor = models.PositiveIntegerField(null=True, blank=True)
    fee_currency = models.CharField(max_length=3, default="KES")
    reason = models.CharField(max_length=300, blank=True)  # rejection or cancellation
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [models.Index(fields=["venue", "starts_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="table_booking_ends_after_start"
            ),
        ]

    def __str__(self):
        return f"{self.venue_id} {self.starts_at:%Y-%m-%d %H:%M} ({self.status})"
