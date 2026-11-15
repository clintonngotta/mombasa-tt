from django.db import transaction
from rest_framework import serializers

from .models import MatchResult, PersonalGame, PersonalMatch

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
