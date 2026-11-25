"""Places within a distance of a point (REQ-004, REQ-044): clubs and facility branches near the player.

The point is the player's own position, so it arrives in a request body, never in a URL (URLs are
logged), and it is neither stored nor logged here."""

from math import cos, radians

from django.db.models import F, FloatField, QuerySet, Value
from django.db.models.functions import ACos, Cast, Cos, Greatest, Least, Radians, Sin
from rest_framework import serializers

EARTH_RADIUS_M = 6_371_000
METRES_PER_DEGREE = 111_320
MIN_RADIUS_M = 100
MAX_RADIUS_M = 50_000
# The most places one search returns, nearest first.
MAX_RESULTS = 50


class NearbySearchSerializer(serializers.Serializer):
    """Where to look, how far, and an optional name to narrow it."""

    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    radius_m = serializers.IntegerField(min_value=MIN_RADIUS_M, max_value=MAX_RADIUS_M)
    search = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


def within(queryset: QuerySet, latitude: float, longitude: float, radius_m: int) -> QuerySet:
    """Rows of `queryset` with coordinates inside the circle, each with `distance_m`, nearest first.

    A box around the circle narrows the rows on the indexed columns first; the great-circle distance
    is then worked out for those alone."""
    lat_span = radius_m / METRES_PER_DEGREE
    found = queryset.filter(latitude__gte=latitude - lat_span, latitude__lte=latitude + lat_span)
    shrink = cos(radians(latitude))
    lng_span = radius_m / (METRES_PER_DEGREE * shrink) if shrink > 1e-6 else 360
    # Near a pole or across the 180th meridian the box would wrap, so longitude is left to the distance.
    if longitude - lng_span >= -180 and longitude + lng_span <= 180:
        found = found.filter(longitude__gte=longitude - lng_span, longitude__lte=longitude + lng_span)

    lat = Radians(Cast(F("latitude"), FloatField()))
    lng = Radians(Cast(F("longitude"), FloatField()))
    here_lat = Value(radians(latitude), output_field=FloatField())
    here_lng = Value(radians(longitude), output_field=FloatField())
    one = Value(1.0, output_field=FloatField())
    # Rounding can push the cosine a hair past 1 for a point on top of the player.
    cosine = Least(
        one, Greatest(-one, Cos(here_lat) * Cos(lat) * Cos(lng - here_lng) + Sin(here_lat) * Sin(lat))
    )
    distance = Value(float(EARTH_RADIUS_M), output_field=FloatField()) * ACos(cosine)
    return (
        found.annotate(distance_m=Cast(distance, FloatField()))
        .filter(distance_m__lte=radius_m)
        .order_by("distance_m", "name", "id")
    )
