"""Club activities and RSVPs (REQ-039, TASK-072)."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class Activity(models.Model):
    """Something a club does beyond competitions: a night out, a fun day, a group visit, a practice
    night. Times are instants shown in the organization's timezone. The place is free text: a venue or
    a meeting point, never anybody's location. A cancelled activity keeps its record and its reason."""

    class Kind(models.TextChoices):
        SOCIAL = "social", "Social night"
        FUN_DAY = "fun_day", "Fun day"
        VISIT = "visit", "Group visit"
        MEETING = "meeting", "Meeting"
        PRACTICE = "practice", "Practice night"
        OPEN_DAY = "open_day", "Open day"
        ANNIVERSARY = "anniversary", "Anniversary"
        WORKSHOP = "workshop", "Workshop"
        CLINIC = "clinic", "Coaching clinic"
        AWARDS = "awards", "Award night"
        OTHER = "other", "Other"

    class Audience(models.TextChoices):
        MEMBERS = "members", "All members"
        SELECTED = "selected", "Selected members"
        # Events beyond the membership (REQ-046): a body's seated representatives (of the chosen clubs,
        # or all), people named one by one, or every signed-in player.
        REPRESENTATIVES = "reps", "Invited representatives"
        NAMED = "named", "Named people"
        OPEN = "open", "Open to all players"

    class Status(models.TextChoices):
        DRAFT = "draft"
        PUBLISHED = "published"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="activities"
    )
    title = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.SOCIAL)
    description = models.TextField(max_length=2000, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    place = models.CharField(max_length=200, blank=True)
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.MEMBERS)
    invitees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    # For the representatives audience: whose representatives are invited. Empty means every sender's.
    clubs = models.ManyToManyField("organizations.Organization", blank=True, related_name="+")
    # Most people "going"; beyond it a "going" answer waits on the list. Empty means no limit.
    capacity = models.PositiveIntegerField(null=True, blank=True)
    rsvp_deadline = models.DateTimeField(null=True, blank=True)
    # Shown to every signed-in player, not only the audience. RSVPs stay with the audience.
    public = models.BooleanField(default=False)
    # Phase 1 only says what it costs; nothing is collected or marked paid here.
    cost_note = models.CharField(max_length=200, blank=True)
    # Phase 2 cost sharing (REQ-039): a one-time REQ-023 campaign billing those going their share, with
    # the activity's spending as REQ-024 expenses on it. Without one, `cost_note` is only text.
    campaign = models.OneToOneField(
        "finance.Campaign", on_delete=models.PROTECT, null=True, blank=True, related_name="activity"
    )
    # A planned visit or support activity for a welfare project (REQ-038): never public, and hidden from
    # members with the project.
    welfare_project = models.ForeignKey(
        "finance.WelfareProject", on_delete=models.PROTECT, null=True, blank=True, related_name="activities"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    cancel_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["starts_at", "id"]
        indexes = [models.Index(fields=["organization", "starts_at"])]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="activity_ends_after_start"),
            models.CheckConstraint(
                condition=~Q(status="cancelled") | ~Q(cancel_reason=""), name="activity_cancelled_with_reason"
            ),
        ]

    def __str__(self):
        return self.title


class Rsvp(models.Model):
    """A member's answer. "Going" beyond the capacity is waitlisted; a freed place is not handed on by
    itself: a waitlisted member answers again to take it."""

    class Answer(models.TextChoices):
        GOING = "going"
        MAYBE = "maybe"
        NOT_GOING = "not_going"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="rsvps")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rsvps")
    answer = models.CharField(max_length=10, choices=Answer.choices)
    waitlisted = models.BooleanField(default=False)
    # Attendance (REQ-046): checking in while it runs marks you there; staff mark the rest by hand.
    checked_in_at = models.DateTimeField(null=True, blank=True)
    attended = models.BooleanField(null=True, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    marked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["updated_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["activity", "user"], name="one_rsvp_per_member"),
            models.CheckConstraint(
                condition=Q(answer="going") | Q(waitlisted=False), name="only_going_is_waitlisted"
            ),
        ]

    def __str__(self):
        return f"{self.user_id} {self.answer} {self.activity_id}"
