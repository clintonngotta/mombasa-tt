"""Feedback forms (REQ-055): competition staff build a form, send it to a tournament's attendees, and
read the totals.

A form is a draft until it is sent; sending fixes who may answer and the questions. A template is a form
kept for reuse: it is never sent, only copied. Each recipient answers once and may change their answers
until the form closes. An anonymous form keeps no link from a response to a person that staff can follow.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class FeedbackForm(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        SENT = "sent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="feedback_forms"
    )
    # The tournament whose attendees are asked. A template has none.
    tournament = models.ForeignKey(
        "competitions.Tournament",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="feedback_forms",
    )
    is_template = models.BooleanField(default=False)
    title = models.CharField(max_length=120)
    intro = models.CharField(max_length=1000, blank=True)
    # In order: [{"id", "title", "description", "questions": [{"id", "kind", "text", "help", "required",
    # "choices": [{"id", "text"}]}]}]. The ids are given by the API; answers are keyed by question id.
    sections = models.JSONField(default=list, blank=True)
    anonymous = models.BooleanField(default=False)
    # Who is asked when it is sent.
    to_entrants = models.BooleanField(default=True)
    to_umpires = models.BooleanField(default=False)
    to_staff = models.BooleanField(default=False)
    guests = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    status = models.CharField(max_length=5, choices=Status.choices, default=Status.DRAFT)
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["organization", "is_template"], name="feedback_form_org_template"),
            models.Index(fields=["tournament"], name="feedback_form_tournament"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_template=False) | Q(tournament__isnull=True, status="draft"),
                name="feedback_template_is_never_sent",
            ),
            models.CheckConstraint(
                condition=Q(status="draft") | Q(opens_at__isnull=False, closes_at__gt=F("opens_at")),
                name="feedback_sent_form_has_dates",
            ),
        ]

    def __str__(self):
        return self.title


class FeedbackRecipient(models.Model):
    """Someone asked to answer, fixed when the form is sent. `answered` says only that they did: for an
    anonymous form it is never shown to staff by name."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(FeedbackForm, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feedback_requests"
    )
    answered = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["form", "user"], name="feedback_recipient_once")]
        indexes = [models.Index(fields=["user", "answered"], name="feedback_recipient_user")]

    def __str__(self):
        return f"{self.user_id} asked by {self.form_id}"


class FeedbackResponse(models.Model):
    """One person's answers: {question id: value}. `owner_key` is a keyed hash of the form and the person,
    so they find their own answers again without the row naming them; `respondent` is set only when the
    form isn't anonymous. An anonymous response keeps no times, which could give the person away."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form = models.ForeignKey(FeedbackForm, on_delete=models.CASCADE, related_name="responses")
    owner_key = models.CharField(max_length=64)
    respondent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    answers = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]  # random ids: the order says nothing about who answered when
        constraints = [models.UniqueConstraint(fields=["form", "owner_key"], name="feedback_response_once")]

    def __str__(self):
        return f"Response to {self.form_id}"
