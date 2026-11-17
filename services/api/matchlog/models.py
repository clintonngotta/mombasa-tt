import uuid

from django.conf import settings
from django.db import models


class MatchResult(models.TextChoices):
    """Derived from the set tally; not stored."""

    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


class PersonalMatch(models.Model):
    """A match the player recorded themselves (REQ-037). Owner-only personal data: never feeds
    ratings, standings, public pages or other players' views."""

    class Format(models.TextChoices):
        SINGLES = "singles"
        DOUBLES = "doubles"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="personal_matches"
    )
    played_on = models.DateField()
    label = models.CharField(max_length=40, help_text="Free text chosen by the player, e.g. Friendly.")
    format = models.CharField(max_length=10, choices=Format.choices, default=Format.SINGLES)
    # Free text on purpose: names never link to or notify another player's identity.
    opponent_name = models.CharField(max_length=120, blank=True)
    partner_name = models.CharField(max_length=80, blank=True)
    venue = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True, max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-played_on", "-created_at"]
        indexes = [models.Index(fields=["owner", "-played_on"])]

    def __str__(self):
        return f"{self.played_on} {self.label} vs {self.opponent_name or 'unknown'}"

    def tally(self) -> tuple[int, int]:
        games = list(self.games.all())
        won = sum(1 for g in games if g.my_points > g.opponent_points)
        return won, len(games) - won

    @property
    def result(self) -> MatchResult:
        won, lost = self.tally()
        return MatchResult.WIN if won > lost else MatchResult.LOSS if lost > won else MatchResult.DRAW


class PersonalGame(models.Model):
    match = models.ForeignKey(PersonalMatch, on_delete=models.CASCADE, related_name="games")
    number = models.PositiveSmallIntegerField()
    my_points = models.PositiveSmallIntegerField()
    opponent_points = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["match", "number"], name="matchlog_game_number_unique"),
            models.CheckConstraint(
                condition=~models.Q(my_points=models.F("opponent_points")), name="matchlog_game_has_winner"
            ),
        ]

    def __str__(self):
        return f"Set {self.number}: {self.my_points}-{self.opponent_points}"
