from django.db import transaction
from rest_framework import serializers

from competitions.official import title as entry_title

from .models import MatchNote, MatchResult, PersonalGame, PersonalMatch

MAX_GAMES = 7
MAX_POINTS = 99


class GameSerializer(serializers.ModelSerializer):
    my_points = serializers.IntegerField(min_value=0, max_value=MAX_POINTS)
    opponent_points = serializers.IntegerField(min_value=0, max_value=MAX_POINTS)

    class Meta:
        model = PersonalGame
        fields = ["my_points", "opponent_points"]

    def validate(self, attrs):
        if attrs["my_points"] == attrs["opponent_points"]:
            raise serializers.ValidationError("A set needs a winner; the scores can't be level.")
        return attrs


class PersonalMatchSerializer(serializers.ModelSerializer):
    games = GameSerializer(many=True)
    games_won = serializers.SerializerMethodField()
    games_lost = serializers.SerializerMethodField()
    result = serializers.ChoiceField(choices=MatchResult.choices, read_only=True)
    label = serializers.CharField(max_length=40, trim_whitespace=True)

    class Meta:
        model = PersonalMatch
        fields = [
            "id",
            "played_on",
            "label",
            "format",
            "opponent_name",
            "partner_name",
            "venue",
            "notes",
            "games",
            "games_won",
            "games_lost",
            "result",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_games_won(self, obj) -> int:
        return obj.tally()[0]

    def get_games_lost(self, obj) -> int:
        return obj.tally()[1]

    def validate_games(self, games):
        if not games:
            raise serializers.ValidationError("Add at least one set.")
        if len(games) > MAX_GAMES:
            raise serializers.ValidationError(f"A match has at most {MAX_GAMES} sets.")
        return games

    def validate(self, attrs):
        fmt = attrs.get("format", getattr(self.instance, "format", PersonalMatch.Format.SINGLES))
        if fmt == PersonalMatch.Format.SINGLES:
            attrs["partner_name"] = ""
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        games = validated_data.pop("games")
        match = PersonalMatch.objects.create(owner=self.context["request"].user, **validated_data)
        self._write_games(match, games)
        return match

    @transaction.atomic
    def update(self, instance, validated_data):
        games = validated_data.pop("games", None)
        instance = super().update(instance, validated_data)
        if games is not None:
            instance.games.all().delete()
            self._write_games(instance, games)
        return instance

    @staticmethod
    def _write_games(match, games):
        PersonalGame.objects.bulk_create(
            PersonalGame(match=match, number=i, **g) for i, g in enumerate(games, 1)
        )
        # Drop any prefetched games so the response reflects what was just written.
        getattr(match, "_prefetched_objects_cache", {}).pop("games", None)


class MatchNoteSerializer(serializers.ModelSerializer):
    """The owner's notes on one match, with enough about the match to find it again (REQ-025)."""

    match_id = serializers.UUIDField(required=False, allow_null=True)
    personal_match_id = serializers.UUIDField(required=False, allow_null=True)
    kind = serializers.SerializerMethodField(
        help_text="official: an umpire-scored match; own: self-recorded."
    )
    title = serializers.SerializerMethodField(help_text="The match, in words: sides, or label and opponent.")
    tournament_id = serializers.SerializerMethodField()
    event_id = serializers.SerializerMethodField()
    tournament_name = serializers.SerializerMethodField()

    class Meta:
        model = MatchNote
        fields = [
            "id",
            "match_id",
            "personal_match_id",
            "kind",
            "title",
            "tournament_id",
            "event_id",
            "tournament_name",
            "observations",
            "goals",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_kind(self, note) -> str:
        return "official" if note.match_id else "own"

    def get_title(self, note) -> str:
        if note.match_id:
            sides = [entry_title(note.match.entry_a), entry_title(note.match.entry_b)]
            return " v ".join(side or "To be decided" for side in sides)
        own = note.personal_match
        return f"{own.label} v {own.opponent_name}" if own.opponent_name else own.label

    def get_tournament_id(self, note) -> str | None:
        return str(note.match.draw.event.tournament_id) if note.match_id else None

    def get_event_id(self, note) -> str | None:
        return str(note.match.draw.event_id) if note.match_id else None

    def get_tournament_name(self, note) -> str | None:
        return note.match.draw.event.tournament.name if note.match_id else None


class MatchNoteChangeSerializer(serializers.ModelSerializer):
    """Editing keeps the note on its match: only what it says changes."""

    class Meta:
        model = MatchNote
        fields = ["observations", "goals"]
