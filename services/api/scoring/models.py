import uuid

from django.conf import settings
from django.db import models

from competitions.models import Match, Rubber

from .engine import initial_state


class ScoringStatus(models.TextChoices):
    """Where the scoring of a match or rubber stands, as people are told."""

    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"  # an umpire has it; no point yet
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"  # played to its end, waiting for the umpire to confirm
    CONFIRMED = "confirmed"  # official


class EnginePhase(models.TextChoices):
    """`status` of the scoring engine's state (packages/scoring)."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Scorecard(models.Model):
    """The umpire's sheet for one individual match (REQ-012): a match of a singles or doubles draw, or
    one rubber of a team tie. It holds who is assigned to score it, the events accepted so far and the
    state they add up to. The result becomes official only when the umpire confirms a finished sheet
    and the server has replayed every event itself."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.OneToOneField(
        Match, on_delete=models.CASCADE, null=True, blank=True, related_name="scorecard"
    )
    rubber = models.OneToOneField(
        Rubber, on_delete=models.CASCADE, null=True, blank=True, related_name="scorecard"
    )
    umpire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="scorecards"
    )
    # Changes with every (re)assignment: events sent under an earlier one are refused (REQ-013).
    assignment_id = models.UUIDField(default=uuid.uuid4)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    # The one device scoring it (REQ-013). Empty until a device takes the sheet; another device has to
    # take it over, which issues a new assignment id and cuts the first one off.
    # What a tie's later rubber started with (3.5.2.7), fixed when its first event is accepted, so
    # striking out and re-scoring an earlier rubber never changes how this sheet replays.
    carry = models.JSONField(null=True, blank=True)
    device_id = models.UUIDField(null=True, blank=True)
    device_label = models.CharField(max_length=80, blank=True)
    device_since = models.DateTimeField(null=True, blank=True)
    # The number of events accepted, which is also the sequence number of the last one.
    revision = models.PositiveIntegerField(default=0)
    state = models.JSONField(default=initial_state)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(match__isnull=False, rubber__isnull=True)
                | models.Q(match__isnull=True, rubber__isnull=False),
                name="scorecard_for_a_match_or_a_rubber",
            ),
        ]

    def __str__(self):
        return f"Scorecard {self.id}"

    @property
    def shown_status(self) -> str:
        if self.confirmed_at:
            return ScoringStatus.CONFIRMED
        return {
            EnginePhase.NOT_STARTED: ScoringStatus.ASSIGNED,
            EnginePhase.IN_PROGRESS: ScoringStatus.IN_PROGRESS,
            EnginePhase.COMPLETED: ScoringStatus.FINISHED,
        }[self.state["status"]]

    @property
    def tie_or_match(self) -> Match:
        """The draw match this sheet belongs to: the match itself, or the tie of its rubber."""
        return self.match if self.match_id else self.rubber.match


class ScoreEvent(models.Model):
    """One accepted score event, exactly as the scoring engine takes it. The id is the device's, so a
    retry of the same event is recognised; the sequence orders the stream. Device time is kept for
    later media work and decides nothing."""

    id = models.UUIDField(primary_key=True, editable=False)
    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    payload = models.JSONField()
    device_time = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["scorecard", "sequence"], name="score_event_sequence_once")
        ]

    def __str__(self):
        return f"Event {self.sequence} of {self.scorecard_id}"


class ScoreAssignment(models.Model):
    """The history of who held a sheet and on which device: every assignment by staff, every device
    that took it, every take-over. Nothing here is edited; it is what the organizers read when two
    people say they scored the same match."""

    class Kind(models.TextChoices):
        ASSIGNED = "assigned"  # staff gave the sheet to an umpire
        UNASSIGNED = "unassigned"  # staff took it back
        DEVICE = "device"  # the umpire's device took an unheld sheet
        TAKE_OVER = "take_over"  # the umpire moved it to another device
        RESET = "reset"  # the sheet was emptied: its match is played again after a correction

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name="assignments")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    umpire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    assignment_id = models.UUIDField()
    device_id = models.UUIDField(null=True, blank=True)
    device_label = models.CharField(max_length=80, blank=True)
    revision = models.PositiveIntegerField(default=0)  # how far the sheet had got at that moment
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.kind} {self.scorecard_id}"


class ScoreConflict(models.Model):
    """Score events a device wrote that the server did not accept, because the sheet had been
    reassigned or scored from elsewhere first (REQ-013). They change nothing: the accepted stream
    stands. They are kept so the organizers can see what the device held and decide what to do.
    The id is the device's, so a report sent twice is one report."""

    id = models.UUIDField(primary_key=True, editable=False)
    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name="conflicts")
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    assignment_id = models.UUIDField(null=True, blank=True)  # what the events were written under
    device_id = models.UUIDField(null=True, blank=True)
    device_label = models.CharField(max_length=80, blank=True)
    # [{"id", "sequence", "event", "device_time"}] in the device's order.
    events = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=0)  # the sheet's revision when it was reported
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolution = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Conflict {self.id} on {self.scorecard_id}"


class MatchIncident(models.Model):
    """An incident of a match as it stands on the umpire's sheet (REQ-043): a time-out, a card and its
    penalty points, an adviser's card, a suspension, the expedite system, a retirement or a
    disqualification. Rebuilt from the accepted events after every change, so an incident the umpire
    undid is gone; the events themselves stay as the record of what was sent."""

    class Kind(models.TextChoices):
        TIMEOUT = "timeout"
        TIMEOUT_END = "timeout_end"
        CARD = "card"
        ADVISER_CARD = "adviser_card"
        SUSPENSION = "suspension"
        SUSPENSION_END = "suspension_end"
        EXPEDITE = "expedite"
        RETIRED = "retired"
        DISQUALIFIED = "disqualified"
        WALKOVER = "walkover"

    class Card(models.TextChoices):
        YELLOW = "yellow"  # a warning
        YELLOW_RED = "yellow_red"  # a warning with penalty points
        RED = "red"  # an adviser sent away

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scorecard = models.ForeignKey(Scorecard, on_delete=models.CASCADE, related_name="incidents")
    sequence = models.PositiveIntegerField()  # the event that recorded it
    kind = models.CharField(max_length=14, choices=Kind.choices)
    side = models.CharField(max_length=1, blank=True)
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    card = models.CharField(max_length=10, choices=Card.choices, blank=True)
    penalty_points = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(max_length=20, blank=True)
    note = models.CharField(max_length=200, blank=True)
    game_number = models.PositiveSmallIntegerField()
    score = models.JSONField(default=list)  # the points of the game when it happened, [a, b]
    at = models.DateTimeField()

    class Meta:
        ordering = ["scorecard", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["scorecard", "sequence"], name="one_incident_per_event")
        ]

    def __str__(self):
        return f"{self.kind} at {self.sequence} of {self.scorecard_id}"
