"""Coaching (REQ-047): a player's coach profile, the coaches they train people with, the coach's weekly
availability, sessions booked with them, and comments a coach leaves on a trainee's matches.

A coach is any player who switches on a coach profile. Coaching starts when one side asks and the other
accepts; while it is active the coach reads the trainee's matches (their own match log and official
matches) and the plans the coach gave them. A comment is between the coach who wrote it and the trainee:
nobody else reads it, not club staff, not officials.
"""

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q

from core.timezones import DEFAULT_TIMEZONE
from training.models import Skill


class Level(models.TextChoices):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CoachProfile(models.Model):
    """What players see when they look for a coach. Listed only while `accepting` is on."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coach_profile"
    )
    headline = models.CharField(max_length=120)
    bio = models.TextField(max_length=2000, blank=True)
    levels = ArrayField(models.CharField(max_length=12, choices=Level.choices), default=list, blank=True)
    specialties = ArrayField(models.CharField(max_length=16, choices=Skill.choices), default=list, blank=True)
    # The price of an hour's session, in minor units; empty when the coach doesn't publish one.
    rate_minor = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    region = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=80, blank=True)
    # Availability is entered and bookings are checked in this timezone.
    timezone = models.CharField(max_length=64, default=DEFAULT_TIMEZONE)
    # Clubs where the coach works; their club plans and tournaments appear in the coach's calendar.
    organizations = models.ManyToManyField("organizations.Organization", blank=True, related_name="coaches")
    accepting = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Coach {self.user_id}"


class Coaching(models.Model):
    """A coach and one trainee. Either side asks; the other accepts or declines; either side ends it."""

    class Status(models.TextChoices):
        REQUESTED = "requested"
        ACTIVE = "active"
        DECLINED = "declined"
        ENDED = "ended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coachings_given"
    )
    trainee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coachings")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(coach=F("trainee")), name="coaching_not_self"),
            models.UniqueConstraint(
                fields=["coach", "trainee"],
                condition=Q(status__in=["requested", "active"]),
                name="coaching_one_open",
            ),
        ]

    def __str__(self):
        return f"{self.coach_id} coaches {self.trainee_id} ({self.status})"


class Availability(models.Model):
    """A weekly window when the coach takes sessions, in the coach's timezone."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coach_availability"
    )
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday
    starts = models.TimeField()
    ends = models.TimeField()
    venue = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["weekday", "starts"]
        verbose_name_plural = "availability"
        constraints = [
            models.CheckConstraint(condition=Q(weekday__lte=6), name="availability_weekday"),
            models.CheckConstraint(condition=Q(ends__gt=F("starts")), name="availability_ends_after_start"),
        ]

    def __str__(self):
        return f"{self.weekday} {self.starts}-{self.ends}"


class Booking(models.Model):
    """A session asked for with a coach. The player asks for a time inside the coach's availability; the
    coach confirms or declines. Requested and confirmed bookings hold the time of both people."""

    class Status(models.TextChoices):
        REQUESTED = "requested"
        CONFIRMED = "confirmed"
        DECLINED = "declined"
        CANCELLED = "cancelled"

    HOLDING = (Status.REQUESTED, Status.CONFIRMED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings_taken"
    )
    trainee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings_made"
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    venue = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    reason = models.CharField(max_length=300, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="booking_ends_after_start"),
            models.CheckConstraint(condition=~Q(coach=F("trainee")), name="booking_not_self"),
        ]

    def __str__(self):
        return f"Booking {self.starts_at} ({self.status})"


class MatchComment(models.Model):
    """A coach's comment on one of the trainee's matches: their own match log entry or an official
    match. Read by the coach who wrote it, while they still coach the trainee, and by the trainee."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coach = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    trainee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coach_comments"
    )
    personal_match = models.ForeignKey(
        "matchlog.PersonalMatch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="coach_comments",
    )
    match = models.ForeignKey(
        "competitions.Match", on_delete=models.CASCADE, null=True, blank=True, related_name="coach_comments"
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(personal_match__isnull=False, match__isnull=True)
                | Q(personal_match__isnull=True, match__isnull=False),
                name="match_comment_one_match",
            ),
        ]

    def __str__(self):
        return f"Comment {self.id}"
