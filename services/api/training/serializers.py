from datetime import timedelta

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Drill, Equipment, PlanItem, TrainingPlan

LONGEST_SESSION = timedelta(hours=12)


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = ["blade", "forehand", "backhand", "updated_at"]
        read_only_fields = ["updated_at"]


class DrillSerializer(serializers.ModelSerializer):
    """A drill. Instructions are required; everything else is optional."""

    title = serializers.CharField(max_length=80, trim_whitespace=True)
    instructions = serializers.CharField(max_length=2000, trim_whitespace=True)
    duration_minutes = serializers.IntegerField(min_value=1, max_value=600, required=False, allow_null=True)
    repetitions = serializers.IntegerField(min_value=1, max_value=10000, required=False, allow_null=True)
    library = serializers.SerializerMethodField()

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
            "library",
            "organization",
            "updated_at",
        ]
        read_only_fields = ["id", "library", "organization", "updated_at"]

    def get_library(self, drill) -> str:
        return "club" if drill.organization_id else "personal"


class PlanItemSerializer(serializers.ModelSerializer):
    """A checklist item (no times) or a session (start and end). Its kind is fixed once created."""

    title = serializers.CharField(max_length=120, trim_whitespace=True, required=False, allow_blank=True)
    drill = serializers.UUIDField(source="drill_id", required=False, allow_null=True)
    drill_title = serializers.CharField(source="drill.title", read_only=True, default=None)
    completed = serializers.BooleanField(required=False, write_only=True)

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
        return attrs


class ProgressSerializer(serializers.Serializer):
    done = serializers.IntegerField()
    total = serializers.IntegerField()


class TrainingPlanSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=80, trim_whitespace=True)
    items = PlanItemSerializer(many=True, read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = TrainingPlan
        fields = ["id", "title", "goal", "starts_on", "ends_on", "items", "progress", "created_at"]
        read_only_fields = ["id", "items", "progress", "created_at"]

    @extend_schema_field(ProgressSerializer)
    def get_progress(self, plan) -> dict:
        items = list(plan.items.all())
        return {"done": sum(1 for i in items if i.completed_at), "total": len(items)}

    def validate(self, attrs):
        starts = attrs.get("starts_on", self.instance.starts_on if self.instance else None)
        ends = attrs.get("ends_on", self.instance.ends_on if self.instance else None)
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "The plan ends before it starts."})
        return attrs


class UpcomingSessionSerializer(serializers.ModelSerializer):
    plan = serializers.UUIDField(source="plan_id")
    plan_title = serializers.CharField(source="plan.title")

    class Meta:
        model = PlanItem
        fields = ["id", "plan", "plan_title", "title", "starts_at", "ends_at", "completed_at"]
        read_only_fields = fields
