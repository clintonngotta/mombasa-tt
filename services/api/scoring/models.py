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
