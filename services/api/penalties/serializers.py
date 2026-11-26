from rest_framework import serializers

from .models import Absence, AbsencePenalty, AbsenceRule, PenaltyKind


class StrictPenaltyFields(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", None) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class AbsenceRuleSerializer(serializers.ModelSerializer):
    """One rule: what an absence of this kind costs."""

    class Meta:
        model = AbsenceRule
        fields = [
            "applies_to",
            "kind",
            "suspension_events",
            "points",
            "fine_minor",
            "currency",
            "apology_excuses",
            "active",
            "updated_at",
        ]
        read_only_fields = ["currency", "updated_at"]
        extra_kwargs = {
            "suspension_events": {"min_value": 1, "max_value": 20},
            "points": {"min_value": 1, "max_value": 100},
            "fine_minor": {"min_value": 1, "max_value": 100_000_000},
        }

    def validate(self, attrs):
        kind = attrs.get("kind", PenaltyKind.WARNING)
        if kind == PenaltyKind.SUSPENSION and not attrs.get("suspension_events"):
            raise serializers.ValidationError(
                {"suspension_events": "Say how many events the suspension lasts."}
            )
        if kind == PenaltyKind.POINTS and not attrs.get("points"):
            raise serializers.ValidationError({"points": "Say how many points."})
        return attrs


class AbsenceRulesSerializer(StrictPenaltyFields):
    """The organization's rules: at most one for each kind of absence. Sending the list replaces it."""

    rules = AbsenceRuleSerializer(many=True, max_length=len(Absence.choices))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        known = set(AbsenceRuleSerializer().fields)
        for sent in self.initial_data.get("rules", []):
            if isinstance(sent, dict) and set(sent) - known:
                raise serializers.ValidationError({"rules": "A rule has a field that isn't accepted."})
        kinds = [rule["applies_to"] for rule in attrs["rules"]]
        if len(set(kinds)) != len(kinds):
            raise serializers.ValidationError({"rules": "Give one rule for each kind of absence."})
        return attrs


class AbsencePenaltySerializer(serializers.ModelSerializer):
    """A penalty as governance staff see it."""

    member_name = serializers.CharField(source="member.display_name", read_only=True)
    decided_by_name = serializers.CharField(
        source="decided_by.display_name", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = AbsencePenalty
        fields = [
            "id",
            "member_name",
            "applies_to",
            "what",
            "happened_on",
            "kind",
            "suspension_events",
            "points",
            "fine_minor",
            "currency",
            "status",
            "reason",
            "decided_by_name",
            "decided_at",
            "appeal",
            "appeal_text",
            "appealed_at",
            "appeal_note",
        ]
        read_only_fields = fields


class MyAbsencePenaltySerializer(serializers.ModelSerializer):
    """A member's own penalty, once issued or waived, with whether they may still appeal."""

    organization_name = serializers.CharField(source="organization.name", read_only=True)
    can_appeal = serializers.SerializerMethodField()

    class Meta:
        model = AbsencePenalty
        fields = [
            "id",
            "organization_name",
            "applies_to",
            "what",
            "happened_on",
            "kind",
            "suspension_events",
            "points",
            "fine_minor",
            "currency",
            "status",
            "reason",
            "decided_at",
            "appeal",
            "appeal_text",
            "appeal_note",
            "can_appeal",
        ]
        read_only_fields = fields

    def get_can_appeal(self, penalty) -> bool:
        return penalty.status == AbsencePenalty.Status.ISSUED and not penalty.appeal


class IssueSerializer(StrictPenaltyFields):
    reason = serializers.CharField(
        max_length=300, trim_whitespace=True, allow_blank=True, required=False, default=""
    )


class WaiveSerializer(StrictPenaltyFields):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class AppealSerializer(StrictPenaltyFields):
    text = serializers.CharField(max_length=1000, trim_whitespace=True)


class AppealDecisionSerializer(StrictPenaltyFields):
    upheld = serializers.BooleanField(help_text="True waives the penalty; false leaves it standing.")
    note = serializers.CharField(
        max_length=300, trim_whitespace=True, allow_blank=True, required=False, default=""
    )


class ProposedSerializer(serializers.Serializer):
    proposed = serializers.IntegerField(help_text="How many new penalties were proposed.")
