from django.utils import timezone
from rest_framework import serializers

from facilities.models import Table

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
            "status",
            "invited",
            "accepted",
            "created_at",
        ]
        read_only_fields = ["id", "status", "created_at"]
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
        return tables

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
