from functools import cache
from zoneinfo import available_timezones

from rest_framework import serializers

DEFAULT_TIMEZONE = "Africa/Nairobi"


@cache
def _known() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone(value: str) -> str:
    """An IANA timezone name, e.g. Africa/Nairobi. Dates are entered and shown in it."""
    if value not in _known():
        raise serializers.ValidationError("Choose a timezone such as Africa/Nairobi.")
    return value
