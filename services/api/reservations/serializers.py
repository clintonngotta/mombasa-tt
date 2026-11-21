from rest_framework import serializers

from . import control, service
from .models import TableBlock


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
    automatic = serializers.BooleanField(help_text="Sent by automatic dispatch, not by a person.")
    people = serializers.ListField(child=serializers.CharField(), help_text="Players held with the table.")
    overrides = serializers.ListField(child=serializers.CharField())
    override_reason = serializers.CharField(allow_blank=True)


class ReasonSerializer(serializers.Serializer):
    """One thing that keeps a match from a table, in the words a refusal would use."""

    code = serializers.CharField()
    message = serializers.CharField()
    until = serializers.DateTimeField(allow_null=True, help_text="For a rest: when it is over.")


class QueuedMatchSerializer(serializers.Serializer):
    """A match in the ready queue. `ready` has a free table suggested; `waiting` could be played but
    waits for a table, for a match ahead of it that shares a player, or for staff; `blocked` can't."""

    match_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    label = serializers.CharField()
    a = serializers.CharField()
    b = serializers.CharField()
    planned_at = serializers.DateTimeField(allow_null=True)
    ready_since = serializers.DateTimeField()
    state = serializers.ChoiceField(choices=["ready", "waiting", "blocked"])
    position = serializers.IntegerField(allow_null=True, help_text="Rank among matches playable now.")
    reasons = ReasonSerializer(many=True)
    suggested_table_id = serializers.UUIDField(allow_null=True)
    suggested_table = serializers.CharField(allow_blank=True)


class TableBlockSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=TableBlock.Reason.choices)
    reason_label = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    since = serializers.DateTimeField()
    by = serializers.CharField(allow_blank=True)


class MatchCallStateSerializer(serializers.Serializer):
    """Where the call of the match on a table stands (REQ-043)."""

    called_at = serializers.DateTimeField(help_text="First call; the grace period runs from it.")
    calls = serializers.IntegerField(help_text="How many times it was called to this table.")
    last_called_at = serializers.DateTimeField()
    grace_until = serializers.DateTimeField()
    a_reported_at = serializers.DateTimeField(allow_null=True)
    b_reported_at = serializers.DateTimeField(allow_null=True)
    no_show = serializers.ListField(
        child=serializers.ChoiceField(choices=control.SIDES),
        help_text="Sides not at the table when the grace period ran out. Only the referee awards a "
        "walkover for it.",
    )


class LiveScoreSerializer(serializers.Serializer):
    games_won = serializers.ListField(child=serializers.IntegerField())
    points = serializers.ListField(child=serializers.IntegerField())
    rubber = serializers.IntegerField(allow_null=True, help_text="The rubber being played, for a tie.")
    rubbers_won = serializers.ListField(child=serializers.IntegerField(), required=False)


class BoardTableSerializer(TableStateSerializer):
    state = serializers.ChoiceField(
        choices=[control.FREE, control.CALLED, control.WARMING_UP, control.IN_PLAY, control.BLOCKED],
        help_text="called: sent and waiting for a side; warming_up: both sides at the table, no point "
        "yet; in_play: scoring has started (or another tournament's match holds it); blocked: out of use.",
    )
    block = TableBlockSerializer(allow_null=True)
    call = MatchCallStateSerializer(allow_null=True)
    umpire = serializers.CharField(allow_blank=True)
    score = LiveScoreSerializer(allow_null=True)
    playing = ReservationSerializer(allow_null=True, help_text="This tournament's match on the table.")
    suggested_match_id = serializers.UUIDField(allow_null=True)
    idle_reason = serializers.CharField(allow_blank=True, help_text="Why a free table has no match.")


class BoardSerializer(serializers.Serializer):
    """The dispatch board: the tables, the queue in its fixed order and what is suggested. A suggestion
    is only that: sending it checks everything again."""

    auto_dispatch = serializers.BooleanField()
    in_play = serializers.BooleanField()
    tables = BoardTableSerializer(many=True)
    queue = QueuedMatchSerializer(many=True)
    to_come = serializers.IntegerField(help_text="Matches still waiting for an earlier result.")


class AutoDispatchSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class ArrivalSerializer(serializers.Serializer):
    side = serializers.ChoiceField(choices=control.SIDES)
    undo = serializers.BooleanField(default=False)


class MoveSerializer(serializers.Serializer):
    table_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class BlockSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=TableBlock.Reason.choices)
    note = serializers.CharField(
        max_length=200, trim_whitespace=True, allow_blank=True, required=False, default=""
    )


class DeskEntrySerializer(serializers.Serializer):
    """An accepted entry at the check-in desk."""

    id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    title = serializers.CharField()
    checked_in_at = serializers.DateTimeField(allow_null=True)
    checked_in_by = serializers.CharField(allow_blank=True)


class MatchDayLogSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    at = serializers.DateTimeField()
    action = serializers.CharField()
    action_label = serializers.CharField()
    summary = serializers.CharField()
    reason = serializers.CharField(allow_blank=True)
    actor = serializers.CharField(allow_blank=True, help_text="Empty for automatic dispatch.")
    match_id = serializers.UUIDField(allow_null=True)
    table = serializers.CharField(allow_blank=True)
