import uuid

from django.conf import settings
from django.db import models

from competitions.models import Match, Rubber
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="reservations")
    table = models.ForeignKey(Table, on_delete=models.PROTECT, related_name="reservations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Checks staff chose to set aside when sending the match, and why. Exclusivity is never one of them.
    overrides = models.JSONField(default=list, blank=True)
    override_reason = models.CharField(max_length=300, blank=True)
    ending = models.CharField(max_length=10, choices=Ending.choices, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    release_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["match"], condition=models.Q(status="active"), name="one_active_reservation_per_match"
            ),
        ]

    def __str__(self):
        return f"{self.match_id} on {self.table_id} ({self.status})"


class Hold(models.Model):
    """One table or one person held by a reservation. `active` mirrors the reservation, so the database
    itself refuses a second active hold on the same table or person, whatever races the requests run."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="holds")
    table = models.ForeignKey(Table, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
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
