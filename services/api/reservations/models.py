import uuid

from django.conf import settings
from django.db import models

from competitions.models import Match, Rubber, Tournament
from facilities.models import Table


class Reservation(models.Model):
    """A match on a table (REQ-014): from the moment it is sent there until its result is official or
    staff call it back. While it is active its table and its players are held; a hold is what stops the
    same table or the same person being sent anywhere else, in any event of any organization. Later
    kinds (bookings, training) will hold the same resources through the same table."""

    class Status(models.TextChoices):
        ACTIVE = "active"
        RELEASED = "released"

    class Ending(models.TextChoices):
        DECIDED = "decided"  # the match got its official result
        RECALLED = "recalled"  # staff took it off the table
        CLOSED = "closed"  # its event was completed or cancelled with the match still out
        MOVED = "moved"  # staff moved it to another table, where a new reservation holds it

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="reservations")
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="reservations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Sent by automatic dispatch, not by a person choosing the table.
    automatic = models.BooleanField(default=False)
    # Checks staff chose to set aside when sending the match, and why. Exclusivity is never one of them.
    overrides = models.JSONField(default=list, blank=True)
    override_reason = models.CharField(max_length=300, blank=True)
    ending = models.CharField(max_length=10, choices=Ending.choices, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    release_reason = models.CharField(max_length=300, blank=True)
    # When the match was first called to a table for this stint: when it was sent, or for a match moved
    # here, when it was first sent to the table it came from. The grace period runs from it.
    called_at = models.DateTimeField(null=True, blank=True)
    # When each side reported at the table after being called (REQ-043). A side that hasn't within the
    # event's grace period of the first call is flagged; only the referee then awards a walkover.
    a_reported_at = models.DateTimeField(null=True, blank=True)
    b_reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["match"], condition=models.Q(status="active"), name="one_active_reservation_per_match"
            ),
        ]

    def __str__(self):
        return f"{self.match_id} on {self.table_id} ({self.status})"


class MatchCall(models.Model):
    """A match called to its table (REQ-019 "Called to table"): the first call when it is sent there and
    each time staff call it again. The grace period runs from the first call of the match, which a move
    to another table carries over."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="calls")
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="calls")
    called_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    called_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["called_at", "id"]

    def __str__(self):
        return f"Call of {self.match_id} at {self.called_at}"


class TableBlock(models.Model):
    """A table taken out of use for a while, with the reason (REQ-043 board state "blocked"). Nothing is
    sent to a blocked table, by a person or by automatic dispatch."""

    class Reason(models.TextChoices):
        OUT_OF_SERVICE = "out_of_service", "Out of service"
        CLEANING = "cleaning", "Being cleaned or set up"
        RESERVED = "reserved", "Kept free on purpose"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="blocks")
    reason = models.CharField(max_length=14, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    blocked_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-blocked_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["table"], condition=models.Q(ended_at__isnull=True), name="table_blocked_once"
            )
        ]

    def __str__(self):
        return f"{self.table_id} blocked ({self.reason})"


class Hold(models.Model):
    """One table or one person held by a reservation. `active` mirrors the reservation, so the database
    itself refuses a second active hold on the same table or person, whatever races the requests run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="holds")
    table = models.ForeignKey(Table, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    # For a tie: the rubber this player is held for. Players are held rubber by rubber, not for the tie.
    rubber = models.ForeignKey(Rubber, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(table__isnull=False, user__isnull=True)
                | models.Q(table__isnull=True, user__isnull=False),
                name="hold_is_a_table_or_a_person",
            ),
            models.UniqueConstraint(
                fields=["table"], condition=models.Q(active=True), name="table_held_once"
            ),
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(active=True), name="person_held_once"
            ),
        ]

    def __str__(self):
        return f"Hold of {self.table_id or self.user_id} for {self.reservation_id}"


class TournamentUmpire(models.Model):
    """Someone competition staff picked to umpire at this tournament (user request, 2026-11-22): a
    member of the host or a player entered in it, so players umpire when they have no match. Being
    listed lets them score the tournament's matches, whatever their role in the host."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="umpires")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["added_at"]
        constraints = [
            models.UniqueConstraint(fields=["tournament", "user"], name="tournament_umpire_once"),
        ]

    def __str__(self):
        return f"{self.user_id} umpires at {self.tournament_id}"


class TableUmpire(models.Model):
    """The umpire who takes every match sent to a table during the tournament, until staff change it.
    One umpire per table, and one table per umpire."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="table_umpires")
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="+")
    umpire = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    assigned_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tournament", "table"], name="one_umpire_per_table"),
            models.UniqueConstraint(fields=["tournament", "umpire"], name="one_table_per_umpire"),
        ]

    def __str__(self):
        return f"{self.umpire_id} on {self.table_id}"
