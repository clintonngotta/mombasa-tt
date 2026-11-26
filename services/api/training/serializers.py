import calendar
from datetime import timedelta
from urllib.parse import urlparse

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Drill, Equipment, PlanItem, TrainingPlan

LONGEST_SESSION = timedelta(hours=12)


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = ["blade", "forehand", "backhand", "updated_at"]
        read_only_fields = ["updated_at"]


MAX_PATTERN_STEPS = 12


class PatternStepSerializer(serializers.Serializer):
    """One shot of a drill on the virtual table; see Drill.pattern."""

    hitter = serializers.ChoiceField(choices=["you", "partner"])
    stroke = serializers.CharField(max_length=40, trim_whitespace=True)
    x = serializers.ChoiceField(choices=["left", "center", "right"])
    depth = serializers.ChoiceField(choices=["short", "half", "long"])
    note = serializers.CharField(max_length=80, trim_whitespace=True, required=False, allow_blank=True)


class LibraryChoices:
    STANDARD = "standard"
    PERSONAL = "personal"
    CLUB = "club"
    COACH = "coach"  # another person's drill, read because it is in a plan they gave the reader
    choices = [STANDARD, PERSONAL, CLUB, COACH]


class DrillSerializer(serializers.ModelSerializer):
    """A drill. Instructions are required; everything else is optional."""

    title = serializers.CharField(max_length=80, trim_whitespace=True)
    instructions = serializers.CharField(max_length=2000, trim_whitespace=True)
    coaching_points = serializers.CharField(
        max_length=2000, trim_whitespace=True, required=False, allow_blank=True
    )
    duration_minutes = serializers.IntegerField(min_value=1, max_value=600, required=False, allow_null=True)
    repetitions = serializers.IntegerField(min_value=1, max_value=10000, required=False, allow_null=True)
    # A list field, not a nested serializer: the steps are stored as JSON on the drill.
    pattern = serializers.ListField(
        child=PatternStepSerializer(), required=False, max_length=MAX_PATTERN_STEPS
    )
    library = serializers.SerializerMethodField()
    organization_name = serializers.CharField(source="organization.name", read_only=True, default=None)

    class Meta:
        model = Drill
        fields = [
            "id",
            "title",
            "instructions",
            "focus",
            "duration_minutes",
            "repetitions",
            "equipment",
            "category",
            "level",
            "coaching_points",
            "description",
            "video_url",
            "skills",
            "pattern",
            "library",
            "organization",
            "organization_name",
            "updated_at",
        ]
        read_only_fields = ["id", "library", "organization", "organization_name", "updated_at"]

    def validate_video_url(self, value):
        host = urlparse(value).hostname or ""
        if value and host.removeprefix("www.").removeprefix("m.") not in ("youtube.com", "youtu.be"):
            raise serializers.ValidationError("Link a YouTube video.")
        return value

    @extend_schema_field(serializers.ChoiceField(choices=LibraryChoices.choices))
    def get_library(self, drill) -> str:
        if drill.organization_id:
            return LibraryChoices.CLUB
        if not drill.owner_id:
            return LibraryChoices.STANDARD
        request = self.context.get("request")
        if request is not None and request.user.pk != drill.owner_id:
            return LibraryChoices.COACH
        return LibraryChoices.PERSONAL


MAX_ACTIVITIES = 20


class ActivitySerializer(serializers.Serializer):
    """One part of a session's running order: a warm-up, a drill on the table, work off it, match play or
    the cool-down. A drill fills in the title when none is given."""

    phase = serializers.ChoiceField(choices=PlanItem.Phase.choices)
    title = serializers.CharField(max_length=80, trim_whitespace=True, required=False, allow_blank=True)
    minutes = serializers.IntegerField(min_value=1, max_value=240, required=False, allow_null=True)
    drill = serializers.UUIDField(required=False, allow_null=True)


class PlanItemSerializer(serializers.ModelSerializer):
    """A checklist item (no times) or a session (start and end). Its kind is fixed once created."""

    title = serializers.CharField(max_length=120, trim_whitespace=True, required=False, allow_blank=True)
    drill = serializers.UUIDField(source="drill_id", required=False, allow_null=True)
    drill_title = serializers.CharField(source="drill.title", read_only=True, default=None)
    completed = serializers.BooleanField(required=False, write_only=True)
    activities = serializers.ListField(child=ActivitySerializer(), required=False, max_length=MAX_ACTIVITIES)

    class Meta:
        model = PlanItem
        fields = [
            "id",
            "kind",
            "title",
            "notes",
            "drill",
            "drill_title",
            "order",
            "starts_at",
            "ends_at",
            "completed",
            "completed_at",
            "activities",
        ]
        read_only_fields = ["id", "order", "completed_at", "drill_title"]

    def validate_kind(self, value):
        if self.instance and value != self.instance.kind:
            raise serializers.ValidationError("An item's kind can't change. Add a new item instead.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind") or (self.instance.kind if self.instance else None)
        if kind is None:
            raise serializers.ValidationError({"kind": "Choose checklist or session."})
        starts = attrs.get("starts_at", self.instance.starts_at if self.instance else None)
        ends = attrs.get("ends_at", self.instance.ends_at if self.instance else None)
        if kind == PlanItem.Kind.CHECKLIST:
            if starts or ends:
                raise serializers.ValidationError(
                    {"starts_at": "A checklist item has no time. Add a session."}
                )
        else:
            if not starts:
                raise serializers.ValidationError({"starts_at": "Choose when the session starts."})
            if not ends:
                raise serializers.ValidationError({"ends_at": "Choose when the session ends."})
            if ends <= starts:
                raise serializers.ValidationError({"ends_at": "The session ends before it starts."})
            if ends - starts > LONGEST_SESSION:
                raise serializers.ValidationError({"ends_at": "Keep a session under 12 hours."})
            activities = attrs.get("activities", self.instance.activities if self.instance else [])
            planned = sum(activity.get("minutes") or 0 for activity in activities)
            if planned * 60 > (ends - starts).total_seconds():
                raise serializers.ValidationError(
                    {"activities": f"The activities add up to {planned} minutes, longer than the session."}
                )
        return attrs


class ProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()


class TrainingPlanSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=80, trim_whitespace=True)
    items = PlanItemSerializer(many=True, read_only=True)
    progress = serializers.SerializerMethodField()
    coach_name = serializers.CharField(
        source="coach.display_name", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = TrainingPlan
        fields = [
            "id",
            "title",
            "goal",
            "goal_skills",
            "period",
            "starts_on",
            "ends_on",
            "organization",
            "coach",
            "coach_name",
            "items",
            "progress",
            "created_at",
        ]
        read_only_fields = ["id", "organization", "coach", "coach_name", "items", "progress", "created_at"]

    @extend_schema_field(ProgressSerializer)
    def get_progress(self, plan) -> dict:
        items = list(plan.items.all())
        return {"done": sum(1 for i in items if i.completed_at), "total": len(items)}

    def validate(self, attrs):
        """A day, week or month plan needs its first day and ends when the period does; a custom plan
        takes any dates, or none."""
        period = attrs.get("period", self.instance.period if self.instance else TrainingPlan.Period.CUSTOM)
        starts = attrs.get("starts_on", self.instance.starts_on if self.instance else None)
        ends = attrs.get("ends_on", self.instance.ends_on if self.instance else None)
        if period != TrainingPlan.Period.CUSTOM:
            if not starts:
                raise serializers.ValidationError({"starts_on": f"Choose the first day of the {period}."})
            attrs["starts_on"] = starts
            attrs["ends_on"] = period_end(period, starts)
        elif starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "The plan ends before it starts."})
        return attrs


def period_end(period: str, starts):
    if period == TrainingPlan.Period.DAY:
        return starts
    if period == TrainingPlan.Period.WEEK:
        return starts + timedelta(days=6)
    # A month from the first day: the day before the same date next month (clamped to month ends).
    year, month = (starts.year + 1, 1) if starts.month == 12 else (starts.year, starts.month + 1)
    day = min(starts.day, calendar.monthrange(year, month)[1])
    return starts.replace(year=year, month=month, day=day) - timedelta(days=1)


class UpcomingSessionSerializer(serializers.ModelSerializer):
    plan = serializers.UUIDField(source="plan_id")
    plan_title = serializers.CharField(source="plan.title")

    class Meta:
        model = PlanItem
        fields = ["id", "plan", "plan_title", "title", "starts_at", "ends_at", "completed_at"]
        read_only_fields = fields


class DrillRecommendationSerializer(serializers.Serializer):
    """A drill suggested for a plan's goal, with the goal skills it teaches."""

    drill = DrillSerializer()
    matched = serializers.ListField(child=serializers.CharField())
