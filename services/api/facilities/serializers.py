from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.geography import coordinate_field, directions_field, validate_coordinates

from .models import MAX_TRAINING_HOURS, Table, TrainingHour, Venue


class TableSerializer(serializers.ModelSerializer):
    label = serializers.CharField(max_length=40, trim_whitespace=True)

    class Meta:
        model = Table
        fields = ["id", "label", "position", "active"]
        read_only_fields = ["id", "position"]


class VenueSerializer(serializers.ModelSerializer):
    """A venue with its tables in playing order."""

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    address = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=True, required=False)
    directions = directions_field()
    latitude = coordinate_field(90)
    longitude = coordinate_field(180)
    tables = serializers.SerializerMethodField()

    class Meta:
        model = Venue
        fields = ["id", "name", "town", "address", "directions", "latitude", "longitude", "active", "tables"]
        read_only_fields = ["id", "tables"]

    def validate(self, attrs):
        validate_coordinates(attrs, self.instance)
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
