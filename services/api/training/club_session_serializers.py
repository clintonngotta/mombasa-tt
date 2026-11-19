from django.utils import timezone
from rest_framework import serializers

from facilities.models import Table
from organizations.models import Membership

from .models import ClubSession, SessionInvitation
from .serializers import LONGEST_SESSION


class SessionTableSerializer(serializers.ModelSerializer):
    venue_name = serializers.CharField(source="venue.name", read_only=True)

    class Meta:
        model = Table
        fields = ["id", "label", "venue_name"]


class ClubSessionSerializer(serializers.ModelSerializer):
    """A club session as its training staff see it."""

    table_ids = serializers.PrimaryKeyRelatedField(
        queryset=Table.objects.none(), many=True, write_only=True, source="tables"
    )
    tables = SessionTableSerializer(many=True, read_only=True)
    plan_id = serializers.UUIDField(required=False, allow_null=True)
    invited = serializers.IntegerField(read_only=True)
    accepted = serializers.IntegerField(read_only=True)
    coach_id = serializers.UUIDField(required=False, allow_null=True)
    coach_name = serializers.CharField(source="coach.display_name", read_only=True, default=None)
    fee_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=10_000_000)
    repeat_weeks = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=12,
        write_only=True,
        help_text="On creation: make this many weekly sessions at the same time (a series).",
    )

    class Meta:
        model = ClubSession
        fields = [
            "id",
            "title",
            "notes",
            "plan_id",
            "table_ids",
            "tables",
            "starts_at",
            "ends_at",
            "capacity",
            "coach_id",
            "coach_name",
            "level",
            "fee_minor",
            "fee_currency",
            "open_to_players",
            "series",
            "repeat_weeks",
            "status",
            "invited",
            "accepted",
            "created_at",
        ]
        read_only_fields = ["id", "status", "series", "created_at"]
        extra_kwargs = {"capacity": {"min_value": 1, "max_value": 500}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.context.get("organization")
        if organization is not None:
            self.fields["table_ids"].child_relation.queryset = Table.objects.filter(
                venue__organization=organization, venue__active=True, active=True
            ).select_related("venue")

    def validate_table_ids(self, tables):
        if not tables:
            raise serializers.ValidationError("Choose at least one table.")
        organization = self.context["organization"]
        # A facility keeps its match tables for play and tournaments; training uses training tables.
        if organization.kind in ("facility", "club_facility") and any(t.kind != "training" for t in tables):
            raise serializers.ValidationError("Choose training tables: match tables are kept for play.")
        return tables

    def validate_coach_id(self, coach_id):
        if coach_id is None:
            return None
        organization = self.context["organization"]
        if not Membership.objects.active().filter(organization=organization, user_id=coach_id).exists():
            raise serializers.ValidationError("Choose a coach among the organization's members.")
        return coach_id

    def validate_fee_currency(self, value):
        if not (len(value) == 3 and value.isalpha() and value.isupper()):
            raise serializers.ValidationError("Use a three-letter currency code.")
        return value

    def validate_plan_id(self, plan_id):
        if plan_id and not self.context["organization"].training_plans.filter(pk=plan_id).exists():
            raise serializers.ValidationError("Choose one of the club's training plans.")
        return plan_id

    def validate(self, attrs):
        starts = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if ends <= starts:
            raise serializers.ValidationError({"ends_at": "The session ends after it starts."})
        if ends - starts > LONGEST_SESSION:
            raise serializers.ValidationError({"ends_at": "A session lasts at most 12 hours."})
        if "starts_at" in attrs and starts <= timezone.now():
            raise serializers.ValidationError({"starts_at": "Schedule the session in the future."})
        return attrs


class SessionInvitationSerializer(serializers.ModelSerializer):
    """One invited member, for the club's training staff: answer and attendance."""

    user_id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = SessionInvitation
        fields = ["id", "user_id", "display_name", "status", "responded_at", "attended", "attendance_at"]
        read_only_fields = fields


class InviteSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)


class AttendanceSerializer(serializers.Serializer):
    attended = serializers.BooleanField(allow_null=True, help_text="Null clears the mark.")


class MySessionSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    tables = SessionTableSerializer(many=True, read_only=True)
    full = serializers.SerializerMethodField()

    class Meta:
        model = ClubSession
        fields = [
            "id",
            "organization_id",
            "organization_name",
            "title",
            "notes",
            "tables",
            "starts_at",
            "ends_at",
            "status",
            "full",
        ]
        read_only_fields = fields

    def get_full(self, obj) -> bool:
        if obj.capacity is None:
            return False
        accepted = getattr(obj, "accepted", None)
        if accepted is None:
            accepted = obj.invitations.filter(status=SessionInvitation.Status.ACCEPTED).count()
        return accepted >= obj.capacity


class MySessionInvitationSerializer(serializers.ModelSerializer):
    """A member's own invitation: the session, their answer and whether they were marked present."""

    session = MySessionSerializer(read_only=True)

    class Meta:
        model = SessionInvitation
        fields = ["id", "status", "responded_at", "attended", "session"]
        read_only_fields = fields


class OpenSessionSerializer(serializers.ModelSerializer):
    """A training slot any signed-in player may join (REQ-044, TASK-103)."""

    organization_id = serializers.UUIDField(read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    tables = SessionTableSerializer(many=True, read_only=True)
    coach_name = serializers.CharField(source="coach.display_name", read_only=True, default=None)
    places_left = serializers.SerializerMethodField()
    joined = serializers.SerializerMethodField()

    class Meta:
        model = ClubSession
        fields = [
            "id",
            "organization_id",
            "organization_name",
            "title",
            "notes",
            "tables",
            "starts_at",
            "ends_at",
            "coach_name",
            "level",
            "fee_minor",
            "fee_currency",
            "capacity",
            "places_left",
            "joined",
            "status",
        ]
        read_only_fields = fields

    def _accepted(self, session):
        return [i for i in session.invitations.all() if i.status == SessionInvitation.Status.ACCEPTED]

    def get_places_left(self, session) -> int | None:
        if session.capacity is None:
            return None
        return max(session.capacity - len(self._accepted(session)), 0)

    def get_joined(self, session) -> bool:
        user = self.context["request"].user
        return any(i.user_id == user.pk for i in self._accepted(session))
