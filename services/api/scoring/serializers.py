from rest_framework import serializers

from . import service
from .models import EnginePhase, Scorecard, ScoreEvent, ScoringStatus


class ScoringSummarySerializer(serializers.Serializer):
    """Where the scoring of a match or rubber stands. `can_score` is true only for the umpire assigned
    to it, so nobody else is ever offered a way into the scoring deck (REQ-010)."""

    scorecard_id = serializers.UUIDField(allow_null=True, help_text="Given to the assigned umpire only.")
    status = serializers.ChoiceField(choices=ScoringStatus.choices)
    umpire_name = serializers.CharField(allow_blank=True)
    can_score = serializers.BooleanField()
    can_assign = serializers.BooleanField(help_text="The caller may assign or change the umpire now.")


class UmpireSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class AssignUmpireSerializer(serializers.Serializer):
    """`user_id` null takes the match back from its umpire. `rubber_id` names the rubber of a tie."""

    user_id = serializers.UUIDField(allow_null=True)
    rubber_id = serializers.UUIDField(allow_null=True, required=False)


class DeckPlayerSerializer(serializers.Serializer):
    slot = serializers.ChoiceField(choices=["a1", "a2", "b1", "b2"])
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class DeckSideSerializer(serializers.Serializer):
    title = serializers.CharField()
    players = DeckPlayerSerializer(many=True)


class ScoringConfigSerializer(serializers.Serializer):
    best_of = serializers.IntegerField()
    doubles = serializers.BooleanField()


class ScoringStateSerializer(serializers.Serializer):
    """The canonical state of the scoring engine (packages/scoring)."""

    status = serializers.ChoiceField(choices=EnginePhase.choices)
    game_number = serializers.IntegerField()
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    )
    games_won = serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    points = serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    server = serializers.CharField(allow_null=True)
    receiver = serializers.CharField(allow_null=True)
    first_server = serializers.CharField(allow_null=True)
    first_receiver = serializers.CharField(allow_null=True)
    a_end = serializers.CharField(allow_null=True)
    decider_changed = serializers.BooleanField()
    timeouts = serializers.ListField(child=serializers.BooleanField(), min_length=2, max_length=2)
    winner = serializers.CharField(allow_null=True)


class AcceptedEventSerializer(serializers.ModelSerializer):
    event = serializers.JSONField(source="payload")

    class Meta:
        model = ScoreEvent
        fields = ["id", "sequence", "event", "device_time", "received_at"]
        read_only_fields = fields


class ScorecardSerializer(serializers.ModelSerializer):
    """Everything the deck needs to score one match, for the umpire assigned to it."""

    status = serializers.ChoiceField(choices=ScoringStatus.choices, source="shown_status")
    config = serializers.SerializerMethodField()
    state = ScoringStateSerializer()
    a = serializers.SerializerMethodField()
    b = serializers.SerializerMethodField()
    tournament_id = serializers.SerializerMethodField()
    tournament_name = serializers.SerializerMethodField()
    event_id = serializers.SerializerMethodField()
    event_name = serializers.SerializerMethodField()
    match_id = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    table = serializers.SerializerMethodField()
    events = AcceptedEventSerializer(many=True, read_only=True)

    class Meta:
        model = Scorecard
        fields = [
            "id",
            "assignment_id",
            "revision",
            "status",
            "config",
            "state",
            "a",
            "b",
            "tournament_id",
            "tournament_name",
            "event_id",
            "event_name",
            "match_id",
            "label",
            "table",
            "confirmed_at",
            "events",
        ]
        read_only_fields = fields

    @staticmethod
    def _side(scorecard, side: str) -> dict:
        users = service.players_of(scorecard)[side]
        match = scorecard.tie_or_match
        entry = match.entry_a if side == "a" else match.entry_b
        names = " / ".join(user.display_name for user in users)
        return {
            "title": f"{names} ({entry.team_name})" if scorecard.rubber_id else names,
            "players": [
                {"slot": f"{side}{number}", "id": user.id, "display_name": user.display_name}
                for number, user in enumerate(users, start=1)
            ],
        }

    def get_config(self, scorecard) -> ScoringConfigSerializer:
        return service.config_of(scorecard)

    def get_a(self, scorecard) -> DeckSideSerializer:
        return self._side(scorecard, "a")

    def get_b(self, scorecard) -> DeckSideSerializer:
        return self._side(scorecard, "b")

    def get_tournament_id(self, scorecard) -> serializers.UUIDField:
        return service.event_of(scorecard).tournament_id

    def get_tournament_name(self, scorecard) -> str:
        return service.event_of(scorecard).tournament.name

    def get_event_id(self, scorecard) -> serializers.UUIDField:
        return service.event_of(scorecard).id

    def get_event_name(self, scorecard) -> str:
        return service.event_of(scorecard).name

    def get_match_id(self, scorecard) -> serializers.UUIDField:
        return scorecard.tie_or_match.id

    def get_label(self, scorecard) -> str:
        return service.label_of(scorecard)

    def get_table(self, scorecard) -> str:
        table = scorecard.tie_or_match.table
        return table.label if table else ""


class MyScorecardSerializer(ScorecardSerializer):
    """One of the caller's assignments in a list: the sheet without its event log."""

    class Meta(ScorecardSerializer.Meta):
        fields = [name for name in ScorecardSerializer.Meta.fields if name != "events"]
        read_only_fields = fields


class SentEventSerializer(serializers.Serializer):
    """One score event from the deck: its own id (so a retry is recognised), its place in the stream,
    the engine event itself, and the device's clock, which is kept but decides nothing."""

    id = serializers.UUIDField()
    sequence = serializers.IntegerField(min_value=1)
    event = serializers.JSONField()
    device_time = serializers.DateTimeField(required=False, allow_null=True)


class SubmitEventsSerializer(serializers.Serializer):
    assignment_id = serializers.UUIDField()
    events = serializers.ListField(child=SentEventSerializer(), min_length=1, max_length=service.MAX_BATCH)


class RefusedEventSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    code = serializers.CharField(help_text="A scoring engine code, `sequence_gap` or `sequence_conflict`.")


class SubmitResultSerializer(serializers.Serializer):
    """What the server now holds. `refused` is the first event that stopped the batch, if any; the
    events before it were accepted."""

    accepted = serializers.IntegerField()
    refused = RefusedEventSerializer(allow_null=True)
    revision = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ScoringStatus.choices)
    state = ScoringStateSerializer()


class ConfirmSerializer(serializers.Serializer):
    """The revision the deck shows, so a result is never confirmed over points still on their way."""

    revision = serializers.IntegerField(min_value=0)
