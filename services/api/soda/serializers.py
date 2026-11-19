from rest_framework import serializers

from . import service
from .models import Challenge

STAKE_FIELDS = ("stake_minor", "stake_currency", "stake_note", "challenged_staked", "owed_by_id")


class SodaPlayerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class OutcomeSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=["not_played", "awaiting_confirmation", "disputed", "confirmed", "settled"]
    )
    winner_id = serializers.UUIDField(allow_null=True)
    owed_by_id = serializers.UUIDField(allow_null=True, required=False)


class ResultViewSerializer(serializers.Serializer):
    games = serializers.ListField(child=serializers.ListField(child=serializers.IntegerField()))
    challenger_confirmed = serializers.BooleanField()
    challenged_confirmed = serializers.BooleanField()
    disputed = serializers.BooleanField()
    dispute_reason = serializers.CharField()


class ChallengeSerializer(serializers.ModelSerializer):
    """A challenge as one of its two players sees it. Stake fields appear only while stakes are
    available to these players; anyone else never gets a challenge from this serializer."""

    challenger = SodaPlayerSerializer(read_only=True)
    challenged = SodaPlayerSerializer(read_only=True)
    challenged_id = serializers.UUIDField(write_only=True)
    stake_minor = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=100_000)
    stake_currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, allow_blank=True)
    stake_note = serializers.CharField(max_length=60, required=False, allow_blank=True, trim_whitespace=True)
    result = serializers.SerializerMethodField()
    outcome = serializers.SerializerMethodField()
    mine = serializers.SerializerMethodField(help_text="challenger or challenged: which side the viewer is")

    class Meta:
        model = Challenge
        fields = [
            "id",
            "challenger",
            "challenged",
            "challenged_id",
            "format",
            "challenger_partner",
            "challenged_partner",
            "play_at",
            "proposed_at",
            "place",
            "best_of",
            "message",
            "stake_minor",
            "stake_currency",
            "stake_note",
            "challenged_staked",
            "status",
            "challenger_shares",
            "challenged_shares",
            "result",
            "outcome",
            "mine",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "proposed_at",
            "challenged_staked",
            "status",
            "challenger_shares",
            "challenged_shares",
            "created_at",
        ]
        extra_kwargs = {"best_of": {"min_value": 1, "max_value": 7}}

    def validate_best_of(self, value):
        if value not in (1, 3, 5, 7):
            raise serializers.ValidationError("Best of 1, 3, 5 or 7.")
        return value

    def validate(self, attrs):
        if attrs.get("stake_minor") is not None and not attrs.get("stake_currency"):
            attrs["stake_currency"] = "KES"
        if attrs.get("format") != Challenge.Format.DOUBLES:
            attrs["challenger_partner"] = attrs["challenged_partner"] = ""
        return attrs

    def get_mine(self, challenge) -> str:
        return "challenger" if challenge.challenger_id == self.context["request"].user.pk else "challenged"

    def get_result(self, challenge) -> dict | None:
        result = getattr(challenge, "result", None)
        if result is None:
            return None
        return ResultViewSerializer(
            {
                "games": result.games,
                "challenger_confirmed": result.challenger_confirmed,
                "challenged_confirmed": result.challenged_confirmed,
                "disputed": result.disputed_by_id is not None,
                "dispute_reason": result.dispute_reason,
            }
        ).data

    def get_outcome(self, challenge) -> dict:
        return OutcomeSerializer(service.outcome(challenge)).data

    def to_representation(self, challenge):
        data = super().to_representation(challenge)
        data["challenger"] = {
            "id": str(challenge.challenger_id),
            "display_name": challenge.challenger.display_name,
        }
        data["challenged"] = {
            "id": str(challenge.challenged_id),
            "display_name": challenge.challenged.display_name,
        }
        if not self.context.get("stakes_shown"):
            for field in STAKE_FIELDS:
                data.pop(field, None)
            data["outcome"].pop("owed_by_id", None)
        return data


class AcceptSerializer(serializers.Serializer):
    match_stake = serializers.BooleanField(default=False)


class CounterSerializer(serializers.Serializer):
    play_at = serializers.DateTimeField()


class RecordSerializer(serializers.Serializer):
    games = serializers.ListField(
        child=serializers.ListField(
            child=serializers.IntegerField(min_value=0, max_value=99), min_length=2, max_length=2
        ),
        min_length=1,
        max_length=7,
        help_text="Per game, [challenger's points, challenged's points].",
    )


class DisputeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class ShareSerializer(serializers.Serializer):
    share = serializers.BooleanField()


class SharedChallengeSerializer(serializers.ModelSerializer):
    """What club members see of a challenge both players chose to share: who, when, the result. Never a
    stake."""

    challenger = SodaPlayerSerializer(read_only=True)
    challenged = SodaPlayerSerializer(read_only=True)
    games = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    winner_id = serializers.SerializerMethodField()

    class Meta:
        model = Challenge
        fields = [
            "id",
            "challenger",
            "challenged",
            "format",
            "play_at",
            "status",
            "games",
            "state",
            "winner_id",
        ]
        read_only_fields = fields

    def get_games(self, challenge) -> list[list[int]] | None:
        result = getattr(challenge, "result", None)
        return result.games if result else None

    def get_state(self, challenge) -> str:
        return service.outcome(challenge)["state"]

    def get_winner_id(self, challenge) -> str | None:
        winner = service.outcome(challenge)["winner_id"]
        return str(winner) if winner else None

    def to_representation(self, challenge):
        data = super().to_representation(challenge)
        data["challenger"] = {
            "id": str(challenge.challenger_id),
            "display_name": challenge.challenger.display_name,
        }
        data["challenged"] = {
            "id": str(challenge.challenged_id),
            "display_name": challenge.challenged.display_name,
        }
        return data


class PolicySerializer(serializers.Serializer):
    games_enabled = serializers.BooleanField()
    stakes_enabled = serializers.BooleanField()
    stakes_available = serializers.BooleanField(
        read_only=True, help_text="False while the platform's stake policy gate is off."
    )


class MySodaSettingsSerializer(serializers.Serializer):
    stakes_available = serializers.BooleanField(help_text="Whether stake fields apply for this player.")
    games_enabled = serializers.BooleanField()
