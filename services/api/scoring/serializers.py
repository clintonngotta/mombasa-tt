from rest_framework import serializers

from reservations.serializers import ReservationSerializer

from . import service
from .models import (
    EnginePhase,
    MatchIncident,
    ScoreAssignment,
    Scorecard,
    ScoreConflict,
    ScoreEvent,
    ScoringStatus,
)


class IncidentSerializer(serializers.Serializer):
    """An incident of the match as it stands (REQ-043): what happened, to whom, and at what score."""

    sequence = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=MatchIncident.Kind.choices)
    side = serializers.CharField(allow_blank=True)
    player_name = serializers.CharField(allow_blank=True)
    card = serializers.CharField(allow_blank=True, help_text="yellow, yellow_red or red; empty otherwise.")
    penalty_points = serializers.IntegerField()
    reason = serializers.CharField(allow_blank=True)
    game_number = serializers.IntegerField()
    score = serializers.ListField(child=serializers.IntegerField())
    at = serializers.DateTimeField()


class SheetIncidentSerializer(IncidentSerializer):
    note = serializers.CharField(allow_blank=True, help_text="The umpire's note; on the sheet only.")


class MatchScoreSerializer(serializers.Serializer):
    """A match being scored, as everybody may watch it (REQ-043): the server's replay of the umpire's
    events, with nothing the deck scores with."""

    status = serializers.ChoiceField(choices=["not_started", "in_progress", "completed"])
    outcome = serializers.CharField(
        allow_null=True, help_text="How a finished sheet ended: played, retired, disqualified."
    )
    winner = serializers.ChoiceField(choices=["a", "b"], allow_null=True)
    game_number = serializers.IntegerField()
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField()),
        help_text="Finished games, side a's points first.",
    )
    games_won = serializers.ListField(child=serializers.IntegerField())
    points = serializers.ListField(child=serializers.IntegerField(), help_text="The game in play.")
    server = serializers.ChoiceField(choices=["a", "b"], allow_null=True)
    server_name = serializers.CharField(
        allow_blank=True, help_text="Who serves, named in doubles and singles alike."
    )
    timeouts = serializers.ListField(
        child=serializers.BooleanField(), help_text="Time-out used, side a then b."
    )
    timeout_running = serializers.ListField(child=serializers.BooleanField())
    suspended = serializers.ChoiceField(choices=["a", "b"], allow_null=True)
    expedite = serializers.BooleanField()
    revision = serializers.IntegerField(
        help_text="Grows with every accepted event: a newer score has a higher one."
    )


class LiveCardSerializer(serializers.Serializer):
    side = serializers.ChoiceField(choices=["a", "b"])
    player_name = serializers.CharField(allow_blank=True)
    card = serializers.ChoiceField(choices=MatchIncident.Card.choices)
    penalty_points = serializers.IntegerField()
    adviser = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)
    game_number = serializers.IntegerField()


class LiveMatchSerializer(serializers.Serializer):
    """One match being scored now, for the score strip and the tournament's live page."""

    match_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    round = serializers.CharField()
    table = serializers.CharField(allow_blank=True)
    a = serializers.CharField(allow_blank=True)
    b = serializers.CharField(allow_blank=True)
    rubber = serializers.IntegerField(allow_null=True, help_text="The rubber being played, in a team tie.")
    rubbers_won = serializers.ListField(child=serializers.IntegerField(), allow_null=True)
    score = MatchScoreSerializer()
    cards = LiveCardSerializer(many=True)


class ScoringSummarySerializer(serializers.Serializer):
    """Where the scoring of a match or rubber stands. `can_score` is true only for the umpire assigned
    to it, so nobody else is ever offered a way into the scoring deck (REQ-010)."""

    scorecard_id = serializers.UUIDField(allow_null=True, help_text="Given to the assigned umpire only.")
    status = serializers.ChoiceField(choices=ScoringStatus.choices)
    umpire_name = serializers.CharField(allow_blank=True)
    can_score = serializers.BooleanField()
    can_assign = serializers.BooleanField(help_text="The caller may assign or change the umpire now.")
    incidents = IncidentSerializer(many=True, help_text="Time-outs, cards and other incidents so far.")
    live = MatchScoreSerializer(allow_null=True, help_text="The score so far, once scoring has started.")


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


class OffencesSerializer(serializers.Serializer):
    a1 = serializers.IntegerField()
    a2 = serializers.IntegerField()
    b1 = serializers.IntegerField()
    b2 = serializers.IntegerField()


class CarrySerializer(serializers.Serializer):
    """What a tie's later rubber starts with: offences by position in this match and adviser cards."""

    offences = OffencesSerializer()
    advisers = serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)


class ScoringConfigSerializer(serializers.Serializer):
    best_of = serializers.IntegerField()
    doubles = serializers.BooleanField()
    carry = CarrySerializer(required=False, help_text="A team tie's later rubber only (3.5.2.7).")


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
    # Incidents (TASK-083). A sheet saved before them reads with the defaults.
    outcome = serializers.CharField(
        allow_null=True, default=None, help_text="played, retired or disqualified."
    )
    timeout_running = serializers.ListField(child=serializers.BooleanField(), default=[False, False])
    offences = OffencesSerializer(default={"a1": 0, "a2": 0, "b1": 0, "b2": 0})
    advisers = serializers.ListField(child=serializers.IntegerField(), default=[0, 0])
    suspended = serializers.CharField(allow_null=True, default=None)
    expedite = serializers.BooleanField(default=False)


class AcceptedEventSerializer(serializers.ModelSerializer):
    event = serializers.JSONField(source="payload")

    class Meta:
        model = ScoreEvent
        fields = ["id", "sequence", "event", "device_time", "received_at"]
        read_only_fields = fields


class DeviceSerializer(serializers.Serializer):
    """Which device is scoring the sheet. `here` compares with the caller's X-Device-Id header."""

    held = serializers.BooleanField(help_text="A device has taken the sheet.")
    here = serializers.BooleanField(help_text="It is the caller's device.")
    label = serializers.CharField(allow_blank=True)
    since = serializers.DateTimeField(allow_null=True)


class ScorecardSerializer(serializers.ModelSerializer):
    """Everything the deck needs to score one match, for the umpire assigned to it."""

    device = serializers.SerializerMethodField()

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
    incidents = serializers.SerializerMethodField()
    can_disqualify = serializers.SerializerMethodField()

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
            "device",
            "events",
            "incidents",
            "can_disqualify",
        ]
        read_only_fields = fields

    def get_device(self, scorecard) -> DeviceSerializer:
        return {
            "held": scorecard.device_id is not None,
            "here": scorecard.device_id is not None and scorecard.device_id == self.context.get("device_id"),
            "label": scorecard.device_label,
            "since": scorecard.device_since,
        }

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

    def get_incidents(self, scorecard) -> SheetIncidentSerializer(many=True):
        return service.incidents_of(scorecard, with_notes=True)

    def get_can_disqualify(self, scorecard) -> bool:
        """The umpire is also the referee (decision D5): only then does the deck offer a disqualification."""
        request = self.context.get("request")
        return request is not None and service.may_disqualify(scorecard, request.user)

    def get_table(self, scorecard) -> str:
        table = scorecard.tie_or_match.table
        return table.label if table else ""


class MyScorecardsQuerySerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=["open", "done"], default="open")


class MyScorecardSerializer(ScorecardSerializer):
    """One of the caller's assignments in a list: the sheet without its event log, with when and where
    the match is planned once the schedule is published."""

    scheduled_at = serializers.SerializerMethodField()
    planned_table = serializers.SerializerMethodField()
    timezone = serializers.SerializerMethodField()

    class Meta(ScorecardSerializer.Meta):
        fields = [
            name
            for name in ScorecardSerializer.Meta.fields
            if name not in ("events", "incidents", "can_disqualify")
        ] + ["scheduled_at", "planned_table", "timezone"]
        read_only_fields = fields

    def get_scheduled_at(self, scorecard) -> serializers.DateTimeField(allow_null=True):
        return scorecard.tie_or_match.scheduled_at

    def get_timezone(self, scorecard) -> str:
        """The venue's, in which the time is shown (REQ-007)."""
        return service.event_of(scorecard).tournament.timezone

    def get_planned_table(self, scorecard) -> str:
        table = scorecard.tie_or_match.planned_table
        return table.label if table else ""

    def get_config(self, scorecard) -> ScoringConfigSerializer:
        # The list needs the format alone; what a rubber carries in is read on its sheet.
        return service.config_of(scorecard, with_carry=False)


class SentEventSerializer(serializers.Serializer):
    """One score event from the deck: its own id (so a retry is recognised), its place in the stream,
    the engine event itself, and the device's clock, which is kept but decides nothing."""

    id = serializers.UUIDField()
    sequence = serializers.IntegerField(min_value=1)
    event = serializers.JSONField()
    device_time = serializers.DateTimeField(required=False, allow_null=True)
    expected_revision = serializers.IntegerField(
        min_value=0,
        required=False,
        help_text="The server revision the device had seen when it sent this. If the server holds less "
        "than that, its stream is not the one the device built on, and the event is refused.",
    )


class SubmitEventsSerializer(serializers.Serializer):
    assignment_id = serializers.UUIDField()
    events = serializers.ListField(child=SentEventSerializer(), min_length=1, max_length=service.MAX_BATCH)


class RefusedEventSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    code = serializers.CharField(
        help_text="A scoring engine code, `sequence_gap`, `sequence_conflict` or `revision_conflict`."
    )


class SubmitResultSerializer(serializers.Serializer):
    """What the server now holds. `refused` is the first event that stopped the batch, if any; the
    events before it were accepted."""

    accepted = serializers.IntegerField()
    refused = RefusedEventSerializer(allow_null=True)
    revision = serializers.IntegerField()
    status = serializers.ChoiceField(choices=ScoringStatus.choices)
    state = ScoringStateSerializer()


class ConfirmSerializer(serializers.Serializer):
    """The assignment the deck holds (a device cut off by a reassignment can't confirm) and the
    revision it shows (a result is never confirmed over points still on their way)."""

    assignment_id = serializers.UUIDField()
    revision = serializers.IntegerField(min_value=0)


class TakeDeviceSerializer(serializers.Serializer):
    """This device takes the sheet. `take_over` is needed when another device holds it."""

    device_id = serializers.UUIDField()
    label = serializers.CharField(max_length=80, allow_blank=True, required=False, default="")
    take_over = serializers.BooleanField(required=False, default=False)


class ConflictEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sequence = serializers.IntegerField(
        min_value=1, max_value=100_000, help_text="Its place in the stream on the device."
    )
    event = serializers.JSONField()
    device_time = serializers.DateTimeField(required=False, allow_null=True)

    def validate_event(self, event):
        """A score event as the engine knows it: a small object with a known type and short values.
        This is shown to staff, so nothing else is kept."""
        fields = {"type", "side", "player", "server", "receiver", "a_end"}
        if (
            not isinstance(event, dict)
            or event.get("type") not in service.EVENT_TYPES
            or not set(event) <= fields
            or any(not isinstance(value, str) or len(value) > 20 for value in event.values())
        ):
            raise serializers.ValidationError("Not a score event.")
        return event


class ConflictReportSerializer(serializers.Serializer):
    """What a device wrote and the server didn't take, sent for the organizers to see. The id is the
    device's own, so sending it twice keeps one report."""

    id = serializers.UUIDField()
    assignment_id = serializers.UUIDField(required=False, allow_null=True)
    device_id = serializers.UUIDField(required=False, allow_null=True)
    device_label = serializers.CharField(max_length=80, allow_blank=True, required=False, default="")
    events = serializers.ListField(
        child=ConflictEventSerializer(), min_length=1, max_length=service.MAX_CONFLICT_EVENTS
    )


class ConflictReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScoreConflict
        fields = ["id", "created_at"]
        read_only_fields = fields


class StreamEventSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    event = serializers.JSONField()


class SheetContextSerializer(serializers.Serializer):
    """Which match a sheet is for, as the organizers' scoring page shows it."""

    scorecard_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    match_id = serializers.UUIDField()
    label = serializers.CharField()
    a = serializers.CharField()
    b = serializers.CharField()


class ScoreConflictSerializer(serializers.Serializer):
    """A device's unaccepted events beside what the server holds at the same places."""

    id = serializers.UUIDField()
    sheet = SheetContextSerializer()
    reported_by = serializers.CharField(allow_blank=True)
    device_label = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    events = StreamEventSerializer(many=True)
    accepted = StreamEventSerializer(many=True, help_text="The official stream at the same sequence numbers.")
    resolved_at = serializers.DateTimeField(allow_null=True)
    resolved_by = serializers.CharField(allow_blank=True)
    resolution = serializers.CharField(allow_blank=True)


class AssignmentStepSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ScoreAssignment.Kind.choices)
    umpire = serializers.CharField(allow_blank=True)
    actor = serializers.CharField(allow_blank=True)
    device_label = serializers.CharField(allow_blank=True)
    revision = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class OpenSheetSerializer(serializers.Serializer):
    """A match being scored, or finished and not yet confirmed by its umpire."""

    sheet = SheetContextSerializer()
    status = serializers.ChoiceField(choices=ScoringStatus.choices)
    umpire = serializers.CharField(allow_blank=True)
    device_label = serializers.CharField(allow_blank=True)
    revision = serializers.IntegerField()
    last_event_at = serializers.DateTimeField(allow_null=True)
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    )
    points = serializers.ListField(child=serializers.IntegerField(), min_length=2, max_length=2)
    history = AssignmentStepSerializer(many=True)


class ScoringOverviewSerializer(serializers.Serializer):
    """What the organizers need to see about scoring in one tournament: sheets still open, and what
    devices reported that the server didn't accept."""

    sheets = OpenSheetSerializer(many=True)
    conflicts = ScoreConflictSerializer(many=True)
    reservations = ReservationSerializer(
        many=True, help_text="Matches on a table: the table and players held until the result is official."
    )


class ResolveConflictSerializer(serializers.Serializer):
    """What was done about it, for the record."""

    note = serializers.CharField(max_length=300, trim_whitespace=True)
