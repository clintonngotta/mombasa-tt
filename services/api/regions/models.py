"""What a regional body does for its region (REQ-048): the yearly agenda, articles to the region's clubs,
meetings, and sponsorships of tournaments.

A regional body is an organization of kind `regional_body` for one catalogue region. Its clubs are the
organizations in the same country and region. Agenda items and published articles reach the members of
those clubs; meetings reach their invitees; a sponsorship is offered to a tournament and its host club
accepts or declines it.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class AgendaItem(models.Model):
    """One date of the body's yearly agenda: a tournament, meeting, event or deadline."""

    class Kind(models.TextChoices):
        TOURNAMENT = "tournament"
        MEETING = "meeting"
        EVENT = "event"
        DEADLINE = "deadline"
        OTHER = "other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="agenda_items"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EVENT)
    title = models.CharField(max_length=120)
    description = models.CharField(max_length=1000, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    tournament = models.ForeignKey(
        "competitions.Tournament", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_on", "title"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_on__gte=F("starts_on")), name="agenda_dates_in_order"),
        ]

    def __str__(self):
        return self.title


class Article(models.Model):
    """News from the body to the clubs of its region: all of them, or the clubs chosen."""

    class Audience(models.TextChoices):
        REGION = "region"
        CHOSEN = "chosen"

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="articles"
    )
    title = models.CharField(max_length=140)
    summary = models.CharField(max_length=280, blank=True)
    body = models.TextField(max_length=10000)
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.REGION)
    clubs = models.ManyToManyField("organizations.Organization", blank=True, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self):
        return self.title


class Meeting(models.Model):
    """A meeting called by an organization (the core of REQ-046): invitees are fixed when it is
    published; they answer, check in while it runs, and read the minutes afterwards."""

    class Kind(models.TextChoices):
        COMMITTEE = "committee"
        GENERAL = "general"
        REPRESENTATIVES = "representatives"
        SPECIAL = "special"

    class Audience(models.TextChoices):
        COMMITTEE = "committee"  # holders of the host's committee positions
        CLUB_ADMINS = "club_admins"  # a regional body's clubs' admins
        MEMBERS = "members"  # every active member of the host
        NAMED = "named"  # the people listed

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="meetings"
    )
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.GENERAL)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True)
    online_link = models.URLField(max_length=300, blank=True)
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.COMMITTEE)
    # The people asked when the audience is `named`; the invitations themselves are MeetingInvitee rows.
    named = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    # The agenda in order: a list of {"title": str, "presenter": str, "tournament": tournament id | null}.
    agenda = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    minutes = models.TextField(max_length=20000, blank=True)
    minutes_recorded_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="meeting_ends_after_start"),
        ]

    def __str__(self):
        return self.title


class MeetingInvitee(models.Model):
    class Answer(models.TextChoices):
        NONE = "none"
        ATTENDING = "attending"
        APOLOGIES = "apologies"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="invitees")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meeting_invitations"
    )
    # Which club they were asked for, when they were asked as a club's admin.
    club = models.ForeignKey(
        "organizations.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    answer = models.CharField(max_length=10, choices=Answer.choices, default=Answer.NONE)
    checked_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__display_name"]
        constraints = [models.UniqueConstraint(fields=["meeting", "user"], name="meeting_invitee_once")]

    def __str__(self):
        return f"{self.user_id} at {self.meeting_id}"


class Sponsorship(models.Model):
    """Money and/or goods an organization offers a tournament. The host club accepts or declines; once
    accepted the sponsor is shown on the tournament."""

    class Status(models.TextChoices):
        OFFERED = "offered"
        ACCEPTED = "accepted"
        DECLINED = "declined"
        WITHDRAWN = "withdrawn"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sponsor = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="sponsorships"
    )
    tournament = models.ForeignKey(
        "competitions.Tournament", on_delete=models.CASCADE, related_name="sponsorships"
    )
    amount_minor = models.PositiveIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KES")
    # Goods: a list of {"item": str, "quantity": int}.
    in_kind = models.JSONField(default=list, blank=True)
    conditions = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OFFERED)
    reason = models.CharField(max_length=300, blank=True)
    offered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["sponsor", "tournament"],
                condition=Q(status__in=["offered", "accepted"]),
                name="one_open_sponsorship",
            ),
        ]

    def __str__(self):
        return f"{self.sponsor_id} sponsors {self.tournament_id}"
