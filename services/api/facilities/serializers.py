from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.geography import coordinate_field, directions_field, validate_coordinates

from .models import Table, Venue


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
