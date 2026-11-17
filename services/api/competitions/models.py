import uuid

from django.conf import settings
from django.db import models

from facilities.models import Venue
from organizations.models import Organization

MAX_EVENTS = 30


class TournamentQuerySet(models.QuerySet):
    def detailed(self):
        """With host, venue and events (each with its number of accepted entries), for serializing."""
        # Ordered explicitly: an aggregate drops the model's default ordering.
        events = Event.objects.annotate(
            accepted_count=models.Count("entries", filter=models.Q(entries__status="accepted"))
        ).order_by("position", "created_at")
        return self.select_related("organization", "venue").prefetch_related(
            models.Prefetch("events", queryset=events)
        )


class Tournament(models.Model):
    """A competition hosted by one organization at one venue (REQ-007). Its dates are calendar days in
    `timezone`. Drafts exist only for the host's competition staff; from publication on it is visible to
    everyone, which grants nobody the right to run it."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tournaments")
    venue = models.ForeignKey(
        Venue, on_delete=models.PROTECT, null=True, blank=True, related_name="tournaments"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=2000, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    timezone = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    objects = TournamentQuerySet.as_manager()

    class Meta:
        ordering = ["starts_on", "name", "id"]
        indexes = [models.Index(fields=["status", "starts_on"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="tournament_dates_in_order"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_closed(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.CANCELLED}


class Event(models.Model):
    """One competition within a tournament: who enters (players, pairs or teams) and how it is played
    (REQ-007). `revision` counts configuration changes, so a published configuration can be told apart
    from a later one."""

    class Kind(models.TextChoices):
        SINGLES = "singles"
        DOUBLES = "doubles"
        TEAM = "team"

    class Format(models.TextChoices):
        ROUND_ROBIN = "round_robin"
        KNOCKOUT = "knockout"
        GROUPS_KNOCKOUT = "groups_knockout"

    class Seeding(models.TextChoices):
        RATING = "rating"  # by current rating
        MANUAL = "manual"  # staff put the entries in seed order
        NONE = "none"  # unseeded draw

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"

    # What "structure" means for REQ-007: fixed once the event has started.
    STRUCTURE_FIELDS = ("kind", "format", "best_of", "seeding", "group_count", "qualifiers_per_group")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    format = models.CharField(max_length=16, choices=Format.choices)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)  # entries; null = no limit
    best_of = models.PositiveSmallIntegerField(default=5)
    rest_minutes = models.PositiveSmallIntegerField(default=10)
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    # Declared only (REQ-008); payments are recorded in Phase 2.
    entry_fee_minor = models.PositiveIntegerField(default=0)
    entry_fee_currency = models.CharField(max_length=3, default="KES")
    seeding = models.CharField(max_length=10, choices=Seeding.choices, default=Seeding.RATING)
    group_count = models.PositiveSmallIntegerField(null=True, blank=True)  # groups_knockout only
    qualifiers_per_group = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    position = models.PositiveSmallIntegerField(default=0)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.tournament_id})"

    @property
    def is_closed(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.CANCELLED}


class LifecycleEntry(models.Model):
    """Audit trail of a tournament's and its events' state changes (REQ-007): who did what, when and
    why. `snapshot` holds the configuration as it stood at that moment. Entries are never edited."""

    class Action(models.TextChoices):
        PUBLISHED = "published"
        UPDATED = "updated"
        STARTED = "started"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        EVENT_STARTED = "event_started"
        EVENT_COMPLETED = "event_completed"
        EVENT_CANCELLED = "event_cancelled"
        EVENT_REMOVED = "event_removed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="lifecycle")
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    event_name = models.CharField(max_length=80, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True)
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.action} {self.tournament_id}"


MIN_TEAM_ROSTER = 2
MAX_TEAM_ROSTER = 10


class Entry(models.Model):
    """One player, pair or team asking to play an event (REQ-008). Status says where the request stands;
    check-in is tracked on its own and says only that the entry has arrived at the venue. Nothing here
    says anything about payment: the fee is declared on the event and receipts arrive in Phase 2."""

    class Status(models.TextChoices):
        PENDING = "pending"  # waiting for staff
        ACCEPTED = "accepted"  # holds one of the event's places
        WAITLISTED = "waitlisted"  # staff will offer a place if one opens
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"

    # Statuses in which the entry still stands, so its players can't be in another entry of the event.
    LIVE = (Status.PENDING, Status.ACCEPTED, Status.WAITLISTED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="entries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    team_name = models.CharField(max_length=80, blank=True)  # team events only
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Why staff rejected or withdrew it; shown to the entry's players and to staff only.
    reason = models.CharField(max_length=300, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["event", "status"])]

    def __str__(self):
        return f"{self.get_status_display()} entry {self.id} in {self.event_id}"

    @property
    def is_live(self) -> bool:
        return self.status in self.LIVE


class EntryPlayer(models.Model):
    """A player in an entry. `live` mirrors the entry's status so the database itself refuses a player
    in two standing entries of one event, whatever races the requests run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="players")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entry_places")
    position = models.PositiveSmallIntegerField(default=0)
    live = models.BooleanField(default=True)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["entry", "user"], name="entry_player_once"),
            models.UniqueConstraint(
                fields=["event", "user"], condition=models.Q(live=True), name="one_live_entry_per_event"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.entry_id}"
