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


class ActivityHostSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    town = serializers.CharField()


class ClubActivitySerializer(serializers.ModelSerializer):
    """An activity. Members see `my_answer` and the counts; only staff see invitee ids and drafts."""

    title = serializers.CharField(max_length=120, trim_whitespace=True)
    place = serializers.CharField(max_length=200, allow_blank=True, required=False, trim_whitespace=True)
    cost_note = serializers.CharField(max_length=200, allow_blank=True, required=False, trim_whitespace=True)
    invitee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
        max_length=500,
        help_text="For selected members: active members. For named people: members or listed players.",
    )
    club_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        write_only=True,
        max_length=200,
        help_text="For the representatives audience: whose representatives. Empty invites them all.",
    )
    organization = serializers.SerializerMethodField(help_text="The host: its id, name and town.")
    my_checked_in_at = serializers.SerializerMethodField()
    can_check_in = serializers.SerializerMethodField(
        help_text="It is running and it is for you: you may check yourself in."
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
            "organization",
            "title",
            "kind",
            "description",
            "starts_at",
            "ends_at",
            "place",
            "audience",
            "invitee_ids",
            "club_ids",
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
            "my_checked_in_at",
            "can_check_in",
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

    def _for_me(self, activity) -> bool:
        """In the audience, worked out from what the view found once for the whole list."""
        audience, context = activity.audience, self.context
        if audience == Activity.Audience.OPEN:
            return True
        if audience == Activity.Audience.NAMED:
            return activity.pk in context.get("invited", ())
        if audience == Activity.Audience.REPRESENTATIVES:
            mine = context.get("represents", {}).get(activity.organization_id, set())
            chosen = {club.pk for club in activity.clubs.all()}
            return bool(mine & chosen) if chosen else bool(mine)
        if activity.organization_id not in context.get("member_of", ()):
            return False
        return audience == Activity.Audience.MEMBERS or activity.pk in context.get("invited", ())

    def get_can_answer(self, activity) -> bool:
        """In the audience and open."""
        return activity.status == Activity.Status.PUBLISHED and self._for_me(activity)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_my_checked_in_at(self, activity):
        mine = self._mine(activity)
        if mine is None or mine.checked_in_at is None:
            return None
        return serializers.DateTimeField().to_representation(mine.checked_in_at)

    def get_can_check_in(self, activity) -> bool:
        now = timezone.now()
        return (
            activity.status == Activity.Status.PUBLISHED
            and activity.starts_at <= now < activity.ends_at
            and self._for_me(activity)
        )

    @extend_schema_field(ActivityHostSerializer)
    def get_organization(self, activity) -> dict:
        host = activity.organization
        return {"id": host.pk, "name": host.name, "town": host.town}

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
        if audience in (Activity.Audience.SELECTED, Activity.Audience.NAMED):
            chosen = attrs.get("invitee_ids")
            # Changing between the two starts the list again: one is members, the other anyone listed.
            same = self.instance is not None and self.instance.audience == audience
            if chosen is None and same:
                chosen = list(self.instance.invitees.values_list("pk", flat=True))
            if not chosen:
                raise serializers.ValidationError({"invitee_ids": "Choose who is invited."})
        return attrs


class CancelActivitySerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class RsvpRequestSerializer(serializers.Serializer):
    answer = serializers.ChoiceField(choices=Rsvp.Answer.choices)


class AttendeeSerializer(serializers.ModelSerializer):
    """Who answered, as the audience sees it: display names only. Attendance is for the staff."""

    display_name = serializers.CharField(source="user.display_name", read_only=True)
    checked_in_at = serializers.SerializerMethodField()
    attended = serializers.SerializerMethodField()

    class Meta:
        model = Rsvp
        fields = ["id", "display_name", "answer", "waitlisted", "checked_in_at", "attended"]
        read_only_fields = fields

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_checked_in_at(self, rsvp):
        if not self.context.get("staff") or rsvp.checked_in_at is None:
            return None
        return serializers.DateTimeField().to_representation(rsvp.checked_in_at)

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_attended(self, rsvp):
        return rsvp.attended if self.context.get("staff") else None


class MarkAttendanceSerializer(serializers.Serializer):
    """Mark someone who answered (`rsvp`), or someone in the audience who didn't (`user_id`)."""

    rsvp = serializers.UUIDField(required=False)
    user_id = serializers.UUIDField(required=False)
    attended = serializers.BooleanField()

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        if ("rsvp" in attrs) == ("user_id" in attrs):
            raise serializers.ValidationError({"rsvp": "Say who: an answer or a person, not both."})
        return attrs


class ScheduleItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SCHEDULE_KINDS)
    id = serializers.UUIDField()
    title = serializers.CharField()
    detail = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    place = serializers.CharField()
    cancelled = serializers.BooleanField()
