from rest_framework import serializers

from . import service


class DispatchSerializer(serializers.Serializer):
    """Send the match to a table. `overrides` sets aside the check-in or rest check, with a reason;
    nothing sets aside that a table and a player are in one place at a time."""

    table_id = serializers.UUIDField()
    overrides = serializers.ListField(
        child=serializers.ChoiceField(choices=service.OVERRIDABLE), required=False, default=list
    )
    reason = serializers.CharField(max_length=300, trim_whitespace=True, allow_blank=True, required=False)


class RecallSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class TableStateSerializer(serializers.Serializer):
    """One of the tournament's tables and whether a match holds it right now."""

    id = serializers.UUIDField()
    label = serializers.CharField()
    free = serializers.BooleanField()
    held_by = serializers.CharField(allow_blank=True, help_text="Tournament and event of the match on it.")
    since = serializers.DateTimeField(allow_null=True)


class ReservationSerializer(serializers.Serializer):
    """A match on a table: the table and the people held until its result is official."""

    id = serializers.UUIDField()
    table_id = serializers.UUIDField()
    table = serializers.CharField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    match_id = serializers.UUIDField()
    a = serializers.CharField()
    b = serializers.CharField()
    since = serializers.DateTimeField()
    people = serializers.ListField(child=serializers.CharField(), help_text="Players held with the table.")
    overrides = serializers.ListField(child=serializers.CharField())
    override_reason = serializers.CharField(allow_blank=True)
