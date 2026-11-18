import uuid

from django.conf import settings
from django.db import models

from competitions.models import Match, OfficialResult, Rubber

from .elo import START


class Discipline(models.TextChoices):
    SINGLES = "singles"
    DOUBLES = "doubles"


class RatingEvent(models.Model):
    """One player's rating change from one rated match or rubber (REQ-016). The ledger of a discipline
    is every such row in the order its match first got an official result (`accepted_at`), then by
    the match's or rubber's id (`subject_id`), which never changes. The rows are worked out from the
    official results and nothing else: a correction removes the rows from that place on and writes
    them again in the same order. Values keep full precision; only what is shown is rounded."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    discipline = models.CharField(max_length=10, choices=Discipline.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rating_events")
    result = models.ForeignKey(OfficialResult, on_delete=models.CASCADE, related_name="rating_events")
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="rating_events")
    rubber = models.ForeignKey(
        Rubber, on_delete=models.CASCADE, null=True, blank=True, related_name="rating_events"
    )
    accepted_at = models.DateTimeField()  # the result's first official acceptance
    subject_id = models.UUIDField()  # the rubber's id, or the match's
    side = models.CharField(max_length=1)  # "a" or "b"
    won = models.BooleanField()
    before = models.FloatField()
    after = models.FloatField()
    delta = models.FloatField()
    # What the calculation compared: the player's own rating, or for doubles the two pair averages.
    own = models.FloatField()
    opponent = models.FloatField()
    expected = models.FloatField()

    class Meta:
        ordering = ["accepted_at", "subject_id", "side", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["discipline", "subject_id", "user"], name="one_rating_event_per_player_and_match"
            )
        ]
        indexes = [
            models.Index(fields=["discipline", "accepted_at", "subject_id"], name="rating_ledger_order"),
            models.Index(fields=["user", "discipline", "-accepted_at"], name="rating_player_history"),
        ]

    def __str__(self):
        return f"{self.discipline} {self.user_id}: {self.before:.1f} to {self.after:.1f}"


class Rating(models.Model):
    """Where a player's ledger stands in one discipline: the last `after`, with the counts shown next
    to it. Rewritten with the ledger, never changed by itself."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ratings")
    discipline = models.CharField(max_length=10, choices=Discipline.choices)
    rating = models.FloatField(default=START)
    played = models.PositiveIntegerField(default=0)
    won = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "discipline"], name="one_rating_per_player_and_discipline"
            )
        ]
        indexes = [models.Index(fields=["discipline", "-rating"], name="rating_ranking_order")]

    def __str__(self):
        return f"{self.discipline} {self.user_id}: {self.rating:.1f}"
