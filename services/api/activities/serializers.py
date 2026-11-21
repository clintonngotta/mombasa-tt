from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from finance.ledger import OWED_STATUSES

from . import costs
from .models import Activity, Rsvp

LONGEST = timezone.timedelta(days=14)
# What a schedule lists; shared with a facility branch's schedule.
SCHEDULE_KINDS = [("activity", "activity"), ("tournament", "tournament"), ("training", "training")]


class MyShareSerializer(serializers.Serializer):
    outstanding_minor = serializers.IntegerField()
    status = serializers.ChoiceField(choices=OWED_STATUSES)


class CostShareSerializer(serializers.Serializer):
    """The shared cost: what each pays and by when, the viewer's own share, and (finance staff only)
    received, spent and remaining."""

    amount_minor = serializers.IntegerField()
    currency = serializers.CharField()
    due_on = serializers.DateField()
    my_share = MyShareSerializer(allow_null=True)
    received_minor = serializers.IntegerField(allow_null=True)
    spent_minor = serializers.IntegerField(allow_null=True)
    remaining_minor = serializers.IntegerField(allow_null=True)


class ShareCostSerializer(serializers.Serializer):
    """An amount each, or a total split evenly among those going (rounded up to whole units)."""

    amount_minor = serializers.IntegerField(min_value=1, max_value=100_000_000, required=False)
    total_minor = serializers.IntegerField(min_value=1, max_value=1_000_000_000, required=False)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    due_on = serializers.DateField()


class ClubActivitySerializer(serializers.ModelSerializer):
    """An activity. Members see `my_answer` and the counts; only staff see invitee ids and drafts."""

    title = serializers.CharField(max_length=120, trim_whitespace=True)
    place = serializers.CharField(max_length=200, allow_blank=True, required=False, trim_whitespace=True)
    cost_note = serializers.CharField(max_length=200, allow_blank=True, required=False, trim_whitespace=True)
    invitee_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, write_only=True, max_length=500
    )
    welfare_project_id = serializers.UUIDField(
        allow_null=True,
        required=False,
        help_text="The welfare project this visit or support activity is for (REQ-038).",
    )
    going = serializers.SerializerMethodField()
    waitlisted = serializers.SerializerMethodField()
    my_answer = serializers.SerializerMethodField()
    my_waitlisted = serializers.SerializerMethodField()
    can_answer = serializers.SerializerMethodField()
    cost_share = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "id",
            "title",
            "kind",
            "description",
            "starts_at",
            "ends_at",
            "place",
            "audience",
            "invitee_ids",
            "capacity",
            "rsvp_deadline",
            "public",
            "cost_note",
            "welfare_project_id",
            "status",
            "cancel_reason",
            "going",
            "waitlisted",
            "my_answer",
            "my_waitlisted",
            "can_answer",
            "cost_share",
            "published_at",
        ]
        read_only_fields = ["id", "status", "cancel_reason", "published_at"]
        extra_kwargs = {"capacity": {"min_value": 1, "max_value": 2000}}

    def _rsvps(self, activity):
        return list(activity.rsvps.all())

    def get_going(self, activity) -> int:
        return sum(1 for r in self._rsvps(activity) if r.answer == Rsvp.Answer.GOING and not r.waitlisted)

    def get_waitlisted(self, activity) -> int:
        return sum(1 for r in self._rsvps(activity) if r.waitlisted)

    def _mine(self, activity):
        user = self.context["request"].user
        return next((r for r in self._rsvps(activity) if r.user_id == user.pk), None)

    def get_my_answer(self, activity) -> str | None:
        mine = self._mine(activity)
        return mine.answer if mine else None

    def get_my_waitlisted(self, activity) -> bool:
        mine = self._mine(activity)
        return bool(mine and mine.waitlisted)

    def get_can_answer(self, activity) -> bool:
        """In the audience (a member, and the activity is for all members or invites them) and open."""
        if not self.context.get("member") or activity.status != Activity.Status.PUBLISHED:
            return False
        return activity.audience == Activity.Audience.MEMBERS or activity.pk in self.context.get(
            "invited", ()
        )

    @extend_schema_field(CostShareSerializer(allow_null=True))
    def get_cost_share(self, activity):
        if not activity.campaign_id:
            return None
        return costs.summary(
            activity,
            self.context["request"].user,
            self.context.get("today") or timezone.localdate(),
            staff=self.context.get("finance_staff", False),
        )

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts is None or ends is None:
            raise serializers.ValidationError({"starts_at": "Set when it starts and ends."})
        if ends <= starts:
            raise serializers.ValidationError({"ends_at": "It ends after it starts."})
        if ends - starts > LONGEST:
            raise serializers.ValidationError({"ends_at": "An activity lasts at most two weeks."})
        deadline = attrs.get("rsvp_deadline", getattr(self.instance, "rsvp_deadline", None))
        if deadline and deadline > ends:
            raise serializers.ValidationError({"rsvp_deadline": "Answers close before the activity ends."})
        audience = attrs.get("audience", getattr(self.instance, "audience", Activity.Audience.MEMBERS))
        if audience == Activity.Audience.SELECTED:
            chosen = attrs.get("invitee_ids")
            if chosen is None and self.instance is not None:
                chosen = list(self.instance.invitees.values_list("pk", flat=True))
            if not chosen:
                raise serializers.ValidationError({"invitee_ids": "Choose who is invited."})
        return attrs


class CancelActivitySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class RsvpRequestSerializer(serializers.Serializer):
    answer = serializers.ChoiceField(choices=Rsvp.Answer.choices)


class AttendeeSerializer(serializers.ModelSerializer):
    """Who answered, as the audience sees it: display names only."""

    display_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = Rsvp
        fields = ["display_name", "answer", "waitlisted"]
        read_only_fields = fields


class ScheduleItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SCHEDULE_KINDS)
    id = serializers.UUIDField()
    title = serializers.CharField()
    detail = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    place = serializers.CharField()
    cancelled = serializers.BooleanField()
