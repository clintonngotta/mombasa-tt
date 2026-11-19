from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from activities.serializers import SCHEDULE_KINDS
from core.geography import (
    CountryField,
    coordinate_field,
    directions_field,
    validate_coordinates,
    validate_location,
)

from . import profile
from .models import (
    MAX_AMENITIES,
    MAX_CLOSURES,
    MAX_OPENING_HOURS,
    MAX_TRAINING_HOURS,
    Closure,
    OpeningHour,
    Pass,
    Table,
    TrainingHour,
    Venue,
    Visit,
)


class TableSerializer(serializers.ModelSerializer):
    label = serializers.CharField(max_length=40, trim_whitespace=True)

    class Meta:
        model = Table
        fields = ["id", "label", "kind", "position", "active"]
        read_only_fields = ["id", "position"]


class OpeningHourSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpeningHour
        fields = ["weekday", "opens", "closes"]

    def validate_weekday(self, value):
        if value > 6:
            raise serializers.ValidationError("Choose a day of the week.")
        return value

    def validate(self, attrs):
        if attrs["closes"] <= attrs["opens"]:
            raise serializers.ValidationError({"closes": "Closing comes after opening."})
        return attrs


class ClosureSerializer(serializers.ModelSerializer):
    reason = serializers.CharField(max_length=120, allow_blank=True, required=False, trim_whitespace=True)

    class Meta:
        model = Closure
        fields = ["starts_on", "ends_on", "reason"]

    def validate(self, attrs):
        if attrs["ends_on"] < attrs["starts_on"]:
            raise serializers.ValidationError({"ends_on": "The closure ends on or after its first day."})
        return attrs


class VenueHoursSerializer(serializers.Serializer):
    """The whole weekly timetable and list of closures, replaced together."""

    hours = OpeningHourSerializer(many=True, max_length=MAX_OPENING_HOURS)
    closures = ClosureSerializer(many=True, max_length=MAX_CLOSURES)

    def validate_hours(self, hours):
        by_day = sorted(hours, key=lambda h: (h["weekday"], h["opens"]))
        for before, after in zip(by_day, by_day[1:], strict=False):
            if before["weekday"] == after["weekday"] and after["opens"] < before["closes"]:
                raise serializers.ValidationError("Opening times on the same day can't overlap.")
        return hours


class VenueSerializer(serializers.ModelSerializer):
    """A venue with its tables in playing order, and its branch profile (REQ-044)."""

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    country = CountryField(max_length=2, allow_blank=True, required=False)
    region = serializers.CharField(max_length=100, allow_blank=True, required=False)
    address = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=True, required=False)
    directions = directions_field()
    latitude = coordinate_field(90)
    longitude = coordinate_field(180)
    phone = serializers.RegexField(
        r"^\+?[0-9 ()-]{6,30}$",
        max_length=30,
        allow_blank=True,
        required=False,
        error_messages={"invalid": "Enter a phone number."},
    )
    rules = serializers.CharField(max_length=2000, allow_blank=True, required=False, trim_whitespace=True)
    amenities = serializers.ListField(
        child=serializers.CharField(max_length=60, trim_whitespace=True),
        max_length=MAX_AMENITIES,
        required=False,
    )
    tables = serializers.SerializerMethodField()
    opening_hours = OpeningHourSerializer(many=True, read_only=True)
    closures = ClosureSerializer(many=True, read_only=True)

    class Meta:
        model = Venue
        fields = [
            "id",
            "name",
            "country",
            "region",
            "town",
            "address",
            "directions",
            "latitude",
            "longitude",
            "phone",
            "rules",
            "amenities",
            "profile",
            "active",
            "tables",
            "opening_hours",
            "closures",
        ]
        read_only_fields = ["id", "tables", "opening_hours", "closures"]

    def validate_amenities(self, amenities):
        cleaned = list(dict.fromkeys(a for a in amenities if a))
        return cleaned

    def validate(self, attrs):
        validate_coordinates(attrs, self.instance)
        validate_location(attrs, self.instance, city_field="town", legacy_town=True)
        return attrs

    @extend_schema_field(TableSerializer(many=True))
    def get_tables(self, venue):
        tables = venue.tables.all()
        if not self.context.get("staff"):
            tables = [table for table in tables if table.active]
        return TableSerializer(tables, many=True).data


class VenueSummarySerializer(serializers.ModelSerializer):
    """What anyone who can see a tournament sees of its venue, including how to find it."""

    latitude = coordinate_field(90)
    longitude = coordinate_field(180)

    class Meta:
        model = Venue
        fields = ["id", "name", "town", "address", "directions", "latitude", "longitude"]
        read_only_fields = fields


class TrainingHourSerializer(serializers.ModelSerializer):
    """A weekly training time. `venue` is one of the organization's venues in use, or none."""

    label = serializers.CharField(max_length=80, allow_blank=True, required=False, trim_whitespace=True)
    venue = serializers.PrimaryKeyRelatedField(queryset=Venue.objects.all(), allow_null=True, required=False)
    venue_name = serializers.CharField(source="venue.name", read_only=True, default=None)

    class Meta:
        model = TrainingHour
        fields = ["id", "weekday", "starts", "ends", "label", "venue", "venue_name"]
        read_only_fields = ["id", "venue_name"]

    def validate_weekday(self, value):
        if value > 6:
            raise serializers.ValidationError("Choose a day of the week.")
        return value

    def validate(self, attrs):
        if attrs["ends"] <= attrs["starts"]:
            raise serializers.ValidationError({"ends": "Training ends before it starts."})
        venue = attrs.get("venue")
        organization = self.context["organization"]
        if venue is not None and (venue.organization_id != organization.id or not venue.active):
            raise serializers.ValidationError({"venue": "Choose one of the club's venues in use."})
        return attrs


class TrainingHourListSerializer(serializers.Serializer):
    hours = TrainingHourSerializer(many=True, max_length=MAX_TRAINING_HOURS)


class PassSerializer(serializers.ModelSerializer):
    """A price at a branch (REQ-044): amounts are integer minor units with their currency."""

    name = serializers.CharField(max_length=80, trim_whitespace=True)
    amount_minor = serializers.IntegerField(min_value=0, max_value=10_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)
    benefits = serializers.ListField(
        child=serializers.CharField(max_length=80, trim_whitespace=True), max_length=12, required=False
    )

    class Meta:
        model = Pass
        fields = [
            "id",
            "name",
            "kind",
            "amount_minor",
            "currency",
            "sessions",
            "valid_days",
            "benefits",
            "active",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "sessions": {"min_value": 2, "max_value": 100},
            "valid_days": {"min_value": 1, "max_value": 366},
        }

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        if self.instance is not None and "kind" in attrs and attrs["kind"] != self.instance.kind:
            raise serializers.ValidationError({"kind": "A price keeps its kind. Add a new one instead."})
        if kind == Pass.Kind.SESSIONS:
            for field in ("sessions", "valid_days"):
                if attrs.get(field, getattr(self.instance, field, None)) is None:
                    raise serializers.ValidationError({field: "A sessions bundle needs this."})
        else:
            attrs["sessions"] = None
            attrs["valid_days"] = None
        if "benefits" in attrs:
            attrs["benefits"] = list(dict.fromkeys(b for b in attrs["benefits"] if b))
        return attrs


class FacilitySerializer(serializers.ModelSerializer):
    """A facility branch as players find it (REQ-044)."""

    organization_id = serializers.UUIDField(read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    latitude = coordinate_field(90)
    longitude = coordinate_field(180)
    open_now = serializers.SerializerMethodField()
    match_tables = serializers.SerializerMethodField()
    training_tables = serializers.SerializerMethodField()

    class Meta:
        model = Venue
        fields = [
            "id",
            "name",
            "organization_id",
            "organization_name",
            "country",
            "region",
            "town",
            "address",
            "directions",
            "latitude",
            "longitude",
            "amenities",
            "open_now",
            "match_tables",
            "training_tables",
        ]
        read_only_fields = fields

    def get_open_now(self, venue) -> bool:
        return profile.is_open(venue, self.context.get("now"))

    def _count(self, venue, kind):
        return sum(1 for t in venue.tables.all() if t.active and t.kind == kind)

    def get_match_tables(self, venue) -> int:
        return self._count(venue, "match")

    def get_training_tables(self, venue) -> int:
        return self._count(venue, "training")


class FacilityProfileSerializer(FacilitySerializer):
    """The whole published profile of one branch: hours, closures coming up, rules and contact."""

    timezone = serializers.CharField(source="organization.timezone", read_only=True)
    opening_hours = OpeningHourSerializer(many=True, read_only=True)
    closures = serializers.SerializerMethodField()
    closed_today = serializers.SerializerMethodField()
    passes = serializers.SerializerMethodField()

    class Meta(FacilitySerializer.Meta):
        fields = [
            *FacilitySerializer.Meta.fields,
            "phone",
            "rules",
            "timezone",
            "opening_hours",
            "closures",
            "closed_today",
            "passes",
        ]
        read_only_fields = fields

    @extend_schema_field(PassSerializer(many=True))
    def get_passes(self, venue):
        return PassSerializer([p for p in venue.passes.all() if p.active], many=True).data

    @extend_schema_field(ClosureSerializer(many=True))
    def get_closures(self, venue):
        today = profile.local_now(venue, self.context.get("now")).date()
        return ClosureSerializer([c for c in venue.closures.all() if c.ends_on >= today], many=True).data

    @extend_schema_field(ClosureSerializer(allow_null=True))
    def get_closed_today(self, venue):
        found = profile.closure_on(venue, profile.local_now(venue, self.context.get("now")).date())
        return ClosureSerializer(found).data if found else None


class VisitSerializer(serializers.ModelSerializer):
    """A door visit as the facility's staff see it, walk-in names included."""

    pass_name = serializers.CharField(source="pass_sold.name", read_only=True)
    pass_kind = serializers.CharField(source="pass_sold.kind", read_only=True)
    player_id = serializers.UUIDField(read_only=True, allow_null=True)
    player_name = serializers.CharField(source="player.display_name", read_only=True, default=None)
    recorded_by_name = serializers.CharField(source="recorded_by.display_name", read_only=True, default=None)
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            "id",
            "pass_name",
            "pass_kind",
            "player_id",
            "player_name",
            "walk_in_name",
            "amount_minor",
            "currency",
            "method",
            "reference",
            "visited_on",
            "valid_until",
            "recorded_by_name",
            "recorded_at",
            "reversed",
            "reversed_at",
            "reversal_reason",
        ]
        read_only_fields = fields

    def get_reversed(self, visit) -> bool:
        return visit.reversed_at is not None


class RecordVisitSerializer(serializers.Serializer):
    pass_id = serializers.UUIDField(required=False, allow_null=True)
    player_id = serializers.UUIDField(required=False, allow_null=True)
    walk_in_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, trim_whitespace=True
    )
    method = serializers.ChoiceField(choices=Visit.Method.choices)
    reference = serializers.CharField(max_length=60, required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        if not attrs.get("player_id") and not attrs.get("walk_in_name"):
            raise serializers.ValidationError({"player_id": "Choose the player, or type the visitor's name."})
        if attrs["method"] != Visit.Method.PASS and not attrs.get("pass_id"):
            raise serializers.ValidationError({"pass_id": "Choose what they paid for."})
        return attrs


class ReverseVisitSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class MyVisitSerializer(serializers.ModelSerializer):
    """The player's own visit or pass at a facility: never anybody else's, never a walk-in name."""

    facility_name = serializers.CharField(source="venue.organization.name", read_only=True)
    venue_id = serializers.UUIDField(read_only=True)
    venue_name = serializers.CharField(source="venue.name", read_only=True)
    pass_name = serializers.CharField(source="pass_sold.name", read_only=True)
    pass_kind = serializers.CharField(source="pass_sold.kind", read_only=True)
    sessions = serializers.IntegerField(source="pass_sold.sessions", read_only=True, allow_null=True)
    benefits = serializers.ListField(
        source="pass_sold.benefits", child=serializers.CharField(), read_only=True
    )
    on_pass = serializers.SerializerMethodField()
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            "id",
            "facility_name",
            "venue_id",
            "venue_name",
            "pass_name",
            "pass_kind",
            "sessions",
            "benefits",
            "amount_minor",
            "currency",
            "method",
            "visited_on",
            "valid_until",
            "on_pass",
            "reversed",
        ]
        read_only_fields = fields

    def get_on_pass(self, visit) -> bool:
        return visit.covered_by_id is not None

    def get_reversed(self, visit) -> bool:
        return visit.reversed_at is not None


class TakingsRowSerializer(serializers.Serializer):
    currency = serializers.CharField()
    amount_minor = serializers.IntegerField()
    visits = serializers.IntegerField()


class TakingsDaySerializer(TakingsRowSerializer):
    day = serializers.DateField()


class TakingsBranchSerializer(TakingsRowSerializer):
    venue_id = serializers.UUIDField()
    venue_name = serializers.CharField()


class TakingsMethodSerializer(TakingsRowSerializer):
    method = serializers.ChoiceField(choices=Visit.Method.choices)


class TakingsPassSerializer(TakingsRowSerializer):
    pass_id = serializers.UUIDField()
    pass_name = serializers.CharField()


class TakingsSerializer(serializers.Serializer):
    """A month's takings, reversed visits left out; each total is per currency."""

    month = serializers.CharField(help_text="YYYY-MM, in the organization's timezone")
    total = TakingsRowSerializer(many=True)
    by_day = TakingsDaySerializer(many=True)
    by_branch = TakingsBranchSerializer(many=True)
    by_method = TakingsMethodSerializer(many=True)
    by_pass = TakingsPassSerializer(many=True)
    reversed = serializers.IntegerField(help_text="Visits reversed that month, not counted above")


class BranchScheduleItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SCHEDULE_KINDS)
    id = serializers.UUIDField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
