import re

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from facilities.models import Table, Venue
from organizations.models import Membership

from . import check_in
from .models import MAX_RADIUS_M, WEEKDAYS, ClubSession, SessionInvitation, TrainingRules
from .serializers import LONGEST_SESSION


class StrictFields(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", None) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class SessionPlaceSerializer(serializers.Serializer):
    """Where a session is held, as members see it: a name and whether it moved. Never coordinates."""

    label = serializers.CharField(allow_blank=True)
    moved = serializers.BooleanField()


class CheckInWindowSerializer(serializers.Serializer):
    opens_at = serializers.DateTimeField()
    closes_at = serializers.DateTimeField()
    late_after = serializers.DateTimeField()
    radius_m = serializers.IntegerField()
    place = SessionPlaceSerializer(
        allow_null=True, help_text="Null: no location is set, so staff mark by hand."
    )


def check_in_info(session, rules) -> dict:
    place = check_in.location_of(session, rules)
    return {
        **check_in.window(session, rules),
        "radius_m": rules.radius_m,
        "place": {"label": place["label"], "moved": place["moved"]} if place else None,
    }


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
    check_in = serializers.SerializerMethodField(
        help_text="When members may check in, from how far, and where the session is held."
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
            "check_in",
            "created_at",
        ]
        read_only_fields = ["id", "status", "series", "created_at"]
        extra_kwargs = {"capacity": {"min_value": 1, "max_value": 500}}

    @extend_schema_field(CheckInWindowSerializer)
    def get_check_in(self, session) -> dict:
        rules = self.context.get("rules") or check_in.rules_for(session.organization)
        return check_in_info(session, rules)

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
        fields = [
            "id",
            "user_id",
            "display_name",
            "status",
            "responded_at",
            "attended",
            "attendance_at",
            "attendance_source",
            "late",
            "check_in_distance_m",
            "check_in_accuracy_m",
        ]
        read_only_fields = fields


class InviteSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)


class AttendanceSerializer(serializers.Serializer):
    attended = serializers.BooleanField(allow_null=True, help_text="Null clears the mark.")
    late = serializers.BooleanField(required=False, default=False, help_text="They came, but late.")


class PositionSerializer(StrictFields):
    """Where the phone says it is, for one check-in. It is compared with the session's location and not
    kept."""

    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    accuracy_m = serializers.FloatField(
        min_value=0, max_value=100_000, help_text="How sure the phone is, in metres (its accuracy radius)."
    )


class SessionLocationSerializer(StrictFields):
    """Where one session is held instead of the usual place: a venue of the organization, or a map
    point. `usual` puts it back."""

    venue_id = serializers.UUIDField(required=False, allow_null=True)
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    label = serializers.CharField(
        max_length=120, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    usual = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        point = attrs.get("latitude") is not None and attrs.get("longitude") is not None
        half = (attrs.get("latitude") is None) != (attrs.get("longitude") is None)
        chosen = [bool(attrs.get("usual")), bool(attrs.get("venue_id")), point]
        if half or sum(chosen) != 1:
            raise serializers.ValidationError(
                {"venue_id": "Choose a venue, give a map point (latitude and longitude), or the usual place."}
            )
        return attrs


TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class TrainingSlotSerializer(serializers.Serializer):
    weekday = serializers.ChoiceField(choices=[(day, day) for day in WEEKDAYS])
    starts = serializers.RegexField(TIME, help_text="HH:MM on the organization's clock.")
    ends = serializers.RegexField(TIME)
    title = serializers.CharField(
        max_length=80, trim_whitespace=True, allow_blank=True, required=False, default=""
    )

    def validate(self, attrs):
        if attrs["ends"] <= attrs["starts"]:
            raise serializers.ValidationError({"ends": "A slot ends after it starts."})
        return attrs


class RulesVenueSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TrainingRulesSerializer(serializers.ModelSerializer):
    """A club's training rules. Members read them; coordinates are for training staff only."""

    slots = TrainingSlotSerializer(many=True, required=False, max_length=21)
    venue = RulesVenueSerializer(read_only=True, allow_null=True)
    venue_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    location_label = serializers.CharField(
        max_length=120, trim_whitespace=True, allow_blank=True, required=False
    )
    has_location = serializers.SerializerMethodField(
        help_text="A position is known, so members can check themselves in."
    )
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = TrainingRules
        fields = [
            "slots",
            "venue",
            "venue_id",
            "latitude",
            "longitude",
            "location_label",
            "has_location",
            "opens_before_minutes",
            "closes_after_minutes",
            "late_after_minutes",
            "radius_m",
            "can_edit",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
        extra_kwargs = {
            "opens_before_minutes": {"min_value": 0, "max_value": 180},
            "closes_after_minutes": {"min_value": 5, "max_value": 240},
            "late_after_minutes": {"min_value": 0, "max_value": 240},
            "radius_m": {"min_value": 25, "max_value": MAX_RADIUS_M},
            "latitude": {"min_value": -90, "max_value": 90},
            "longitude": {"min_value": -180, "max_value": 180},
        }

    def get_has_location(self, rules) -> bool:
        venue = rules.venue
        return (venue is not None and venue.latitude is not None) or rules.latitude is not None

    def get_can_edit(self, rules) -> bool:
        return bool(self.context.get("staff"))

    def to_representation(self, rules):
        data = super().to_representation(rules)
        if not self.context.get("staff"):
            data["latitude"] = data["longitude"] = None  # members see the name of the place only
        return data

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        instance = self.instance
        latitude = attrs.get("latitude", getattr(instance, "latitude", None))
        longitude = attrs.get("longitude", getattr(instance, "longitude", None))
        if (latitude is None) != (longitude is None):
            raise serializers.ValidationError({"latitude": "Give both latitude and longitude, or neither."})
        closes = attrs.get("closes_after_minutes", getattr(instance, "closes_after_minutes", 30))
        late = attrs.get("late_after_minutes", getattr(instance, "late_after_minutes", 10))
        if late > closes:
            raise serializers.ValidationError({"late_after_minutes": "Late starts before check-in closes."})
        if "venue_id" in attrs:
            venue_id = attrs.pop("venue_id")
            venue = None
            if venue_id is not None:
                venue = Venue.objects.filter(pk=venue_id, organization=self.context["organization"]).first()
                if venue is None:
                    raise serializers.ValidationError({"venue_id": "Choose one of your venues."})
            attrs["venue"] = venue
        return attrs


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
    check_in = serializers.SerializerMethodField(
        help_text="When you may check in, from how far, and where the session is held."
    )

    class Meta:
        model = SessionInvitation
        fields = [
            "id",
            "status",
            "responded_at",
            "attended",
            "late",
            "attendance_source",
            "attendance_at",
            "check_in",
            "session",
        ]
        read_only_fields = fields

    @extend_schema_field(CheckInWindowSerializer)
    def get_check_in(self, invitation) -> dict:
        session = invitation.session
        cache = self.context.setdefault("rules_by_org", {})
        if session.organization_id not in cache:
            cache[session.organization_id] = check_in.rules_for(session.organization)
        return check_in_info(session, cache[session.organization_id])


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
