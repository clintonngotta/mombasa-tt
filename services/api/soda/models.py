"""Soda games: friendly challenges between two players (REQ-040, TASK-076).

Unrated: nothing here touches Elo, standings, official history or table reservations. A stake is only a
record of what a player pledged to pay if they lose; Coast TT never collects, holds or moves money, and
only the two players can stake. Stakes stay off unless the policy gate (settings.SODA_STAKES_ENABLED,
TASK-078) is on and neither player's organization has switched them off.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Challenge(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"  # waiting for the challenged player
        COUNTERED = "countered"  # the challenged player proposed another time
        ACCEPTED = "accepted"
        DECLINED = "declined"
        WITHDRAWN = "withdrawn"
        PLAYED = "played"  # a result is recorded; see `outcome`

    class Format(models.TextChoices):
        SINGLES = "singles"
        DOUBLES = "doubles"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    challenger = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    challenged = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    format = models.CharField(max_length=8, choices=Format.choices, default=Format.SINGLES)
    # Doubles partners are names only: they are not parties to the challenge or its stake.
    challenger_partner = models.CharField(max_length=80, blank=True)
    challenged_partner = models.CharField(max_length=80, blank=True)
    # Empty means "next time we meet".
    play_at = models.DateTimeField(null=True, blank=True)
    proposed_at = models.DateTimeField(null=True, blank=True)  # the challenged player's counter-time
    place = models.CharField(max_length=120, blank=True)
    best_of = models.PositiveSmallIntegerField(default=3)
    message = models.CharField(max_length=300, blank=True)
    # What the challenger pledges to pay if they lose: an amount, or something like "a soda".
    stake_minor = models.PositiveIntegerField(null=True, blank=True)
    stake_currency = models.CharField(max_length=3, blank=True)
    stake_note = models.CharField(max_length=60, blank=True)
    # The challenged player matched the same stake when accepting.
    challenged_staked = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # Each player chooses whether their clubs' members may see the challenge and its result.
    challenger_shares = models.BooleanField(default=False)
    challenged_shares = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(challenger=models.F("challenged")), name="soda_not_yourself"),
            models.CheckConstraint(condition=Q(best_of__in=[1, 3, 5, 7]), name="soda_best_of"),
            models.CheckConstraint(
                condition=Q(stake_minor__isnull=True) | ~Q(stake_currency=""), name="soda_stake_has_currency"
            ),
        ]

    def __str__(self):
        return f"{self.challenger_id} v {self.challenged_id} ({self.status})"

    @property
    def staked(self) -> bool:
        return self.stake_minor is not None or bool(self.stake_note)


class Result(models.Model):
    """The games as one player recorded them, from the challenger's side ([challenger, challenged] per
    game), and each player's answer. Only a result both confirmed decides the stake; a disputed one owes
    nothing. The winner marks a pledge settled once it's been honoured outside Coast TT."""

    challenge = models.OneToOneField(Challenge, on_delete=models.CASCADE, related_name="result")
    games = models.JSONField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    challenger_confirmed = models.BooleanField(default=False)
    challenged_confirmed = models.BooleanField(default=False)
    disputed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    dispute_reason = models.CharField(max_length=300, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Result of {self.challenge_id}"

    def tally(self) -> tuple[int, int]:
        won = sum(1 for a, b in self.games if a > b)
        return won, len(self.games) - won

    @property
    def confirmed(self) -> bool:
        return self.challenger_confirmed and self.challenged_confirmed and self.disputed_by_id is None


class Policy(models.Model):
    """An organization's switches for its members: soda games at all, and stakes."""

    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.CASCADE, primary_key=True, related_name="soda_policy"
    )
    games_enabled = models.BooleanField(default=True)
    stakes_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"Soda policy of {self.organization_id}"
