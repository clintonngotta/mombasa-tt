"""Equipment, drills and personal training plans (REQ-026, REQ-027; TASK-042, TASK-043)."""

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q


class Skill(models.TextChoices):
    """What a drill teaches, and what a plan's goal is (REQ-026, REQ-027)."""

    FOOTWORK = "footwork", "Footwork"
    PLACEMENT = "placement", "Placement"
    FOREHAND = "forehand", "Forehand"
    BACKHAND = "backhand", "Backhand"
    THIRD_BALL = "third_ball", "Third-ball attack"
    SERVE = "serve", "Serve"
    RECEIVE = "receive", "Receive"
    SHORT_GAME = "short_game", "Short game"
    TOPSPIN = "topspin", "Topspin"
    BLOCKING = "blocking", "Blocking"
    CONSISTENCY = "consistency", "Consistency"
    TRANSITION = "transition", "Forehand-backhand transition"
    READING_SPIN = "reading_spin", "Reading spin"
    FITNESS = "fitness", "Fitness"
    FLEXIBILITY = "flexibility", "Flexibility"


class Equipment(models.Model):
    """What a player plays with, in their own words (REQ-026). Optional and private to them; it makes no
    claim about how well they play."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="equipment"
    )
    blade = models.CharField(max_length=100, blank=True)
    forehand = models.CharField(max_length=100, blank=True)
    backhand = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Equipment of {self.user_id}"


class Drill(models.Model):
    """An exercise in a library (REQ-026): the standard library every signed-in player sees (seeded, no
    owner and no club, read-only), a player's own, private to them, or a club's, which its members see and
    its training staff (training.manage) edit.

    `pattern` is where the balls land, in order, for the virtual table: a list of steps, each
    {"hitter": "you" | "partner", "stroke": "BH", "x": "left" | "center" | "right",
    "depth": "short" | "half" | "long", "note": optional caption}. The ball lands on the side opposite
    the hitter, and `stroke` is the label shown there: the stroke played from that spot ("BH",
    "FH pivot", "FH middle"). `x` is seen from "you", at the near end, so "right" is a right-hander's
    forehand side. Off-table drills (warm-ups, fitness, cool-downs) have no pattern."""

    class Category(models.TextChoices):
        SERVE = "serve"
        RECEIVE = "receive"
        FOOTWORK = "footwork"
        TOPSPIN = "topspin"
        BLOCK = "block"
        SHORT_GAME = "short_game"
        MULTIBALL = "multiball"
        MATCH_PLAY = "match_play"
        WARM_UP = "warm_up"
        OFF_TABLE = "off_table"
        COOL_DOWN = "cool_down"

    class Level(models.TextChoices):
        BEGINNER = "beginner"
        INTERMEDIATE = "intermediate"
        ADVANCED = "advanced"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="drills"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="drills"
    )
    title = models.CharField(max_length=80)
    instructions = models.TextField()
    focus = models.CharField(max_length=80, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    repetitions = models.PositiveSmallIntegerField(null=True, blank=True)
    equipment = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=12, choices=Category.choices, blank=True)
    level = models.CharField(max_length=12, choices=Level.choices, blank=True)
    coaching_points = models.TextField(blank=True)
    # Background: where the drill comes from and what it builds.
    description = models.TextField(blank=True)
    # A YouTube video (or search) showing the drill.
    video_url = models.URLField(max_length=300, blank=True)
    skills = ArrayField(models.CharField(max_length=16, choices=Skill.choices), default=list, blank=True)
    pattern = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "created_at"]
        constraints = [
            # Neither set is the standard library.
            models.CheckConstraint(
                condition=Q(owner__isnull=True) | Q(organization__isnull=True),
                name="drill_one_library",
            ),
        ]

    def __str__(self):
        return self.title


class TrainingPlan(models.Model):
    """A plan (REQ-027): a player's own, with checklist items to tick off and sessions in their calendar,
    or a club's, for a day, a week, a month or any dates, which its members see and its training staff
    write."""

    class Period(models.TextChoices):
        DAY = "day"
        WEEK = "week"
        MONTH = "month"
        CUSTOM = "custom"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="training_plans",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="training_plans",
    )
    title = models.CharField(max_length=80)
    goal = models.CharField(max_length=280, blank=True)
    # What the plan is for; drills teaching these are recommended for it.
    goal_skills = ArrayField(models.CharField(max_length=16, choices=Skill.choices), default=list, blank=True)
    period = models.CharField(max_length=8, choices=Period.choices, default=Period.CUSTOM)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    # The coach who gave this plan to its owner (REQ-047). They read and edit it while they coach them;
    # the owner keeps it, and its progress, whatever happens to the coaching.
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plans_given",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(owner__isnull=False, organization__isnull=True)
                | Q(owner__isnull=True, organization__isnull=False),
                name="training_plan_one_holder",
            ),
        ]

    def __str__(self):
        return self.title


class PlanItem(models.Model):
    """One step of a plan. A checklist item is just ticked off and reserves nothing. A session is a
    commitment in the player's calendar: it may not overlap their other sessions or scheduled matches."""

    class Kind(models.TextChoices):
        CHECKLIST = "checklist"
        SESSION = "session"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(TrainingPlan, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=120)
    notes = models.CharField(max_length=500, blank=True)
    drill = models.ForeignKey(Drill, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    order = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # The session's running order, from warm-up to cool-down: a list of
    # {"phase": Phase, "title": str, "minutes": int | null, "drill": drill id | null}.
    activities = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Phase(models.TextChoices):
        WARM_UP = "warm_up", "Warm-up"
        ON_TABLE = "on_table", "On the table"
        OFF_TABLE = "off_table", "Off the table"
        MATCH_PLAY = "match_play", "Match play"
        COOL_DOWN = "cool_down", "Cool-down"

    class Meta:
        ordering = ["order", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="checklist", starts_at__isnull=True, ends_at__isnull=True)
                | Q(kind="session", starts_at__isnull=False, ends_at__gt=F("starts_at")),
                name="plan_item_times_match_kind",
            ),
        ]

    def __str__(self):
        return self.title
