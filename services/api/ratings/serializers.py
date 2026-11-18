from rest_framework import serializers

from .models import Discipline


class RankingRowSerializer(serializers.Serializer):
    rank = serializers.IntegerField(help_text="Players with the same rating share a rank.")
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    clubs = serializers.ListField(child=serializers.CharField())
    listed = serializers.BooleanField(help_text="The player has a page in the directory.")
    is_me = serializers.BooleanField()
    rating = serializers.FloatField(help_text="Full precision; round only to show it.")
    played = serializers.IntegerField()
    won = serializers.IntegerField()
    form = serializers.ListField(
        child=serializers.ChoiceField(choices=["W", "L"]), help_text="Latest rated matches, newest first."
    )
    last_delta = serializers.FloatField(allow_null=True)


class RankingSerializer(serializers.Serializer):
    discipline = serializers.ChoiceField(choices=Discipline.choices)
    scope = serializers.ChoiceField(choices=["platform", "club"])
    organization_id = serializers.UUIDField(allow_null=True)
    organization_name = serializers.CharField(allow_blank=True)
    processing = serializers.BooleanField(
        help_text="A result has not reached the ratings yet: the table is provisional."
    )
    count = serializers.IntegerField(help_text="Rated players in this scope.")
    rows = RankingRowSerializer(many=True)


class RatingSummarySerializer(serializers.Serializer):
    discipline = serializers.ChoiceField(choices=Discipline.choices)
    rating = serializers.FloatField(allow_null=True, help_text="Null until a rated match is played.")
    played = serializers.IntegerField()
    won = serializers.IntegerField()
    rank = serializers.IntegerField(allow_null=True, help_text="On the platform, in this discipline.")
    ranked = serializers.IntegerField(help_text="How many players the rank is among.")
    form = serializers.ListField(child=serializers.ChoiceField(choices=["W", "L"]))


class RatingChangeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    discipline = serializers.ChoiceField(choices=Discipline.choices)
    at = serializers.DateTimeField(help_text="When the result first became official.")
    won = serializers.BooleanField()
    before = serializers.FloatField()
    after = serializers.FloatField()
    delta = serializers.FloatField()
    expected = serializers.FloatField(help_text="The expected score, 0 to 1.")
    own = serializers.FloatField(help_text="The rating compared: the player's, or the pair's average.")
    opponent = serializers.FloatField(help_text="The opponent's rating, or the other pair's average.")
    partner = serializers.CharField(allow_blank=True)
    opponents = serializers.ListField(child=serializers.CharField())
    games = serializers.ListField(
        child=serializers.ListField(child=serializers.IntegerField()),
        help_text="Points of each game, this player's side first.",
    )
    tournament_id = serializers.UUIDField()
    tournament_name = serializers.CharField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    match_id = serializers.UUIDField()
    rubber = serializers.IntegerField(allow_null=True, help_text="The rubber's number in a team tie.")
    corrected = serializers.BooleanField(help_text="The result it comes from replaced an earlier one.")


class PlayerRatingsSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    processing = serializers.BooleanField()
    summaries = RatingSummarySerializer(many=True)
    discipline = serializers.ChoiceField(choices=Discipline.choices, help_text="The one `history` is of.")
    result = serializers.ChoiceField(choices=["all", "won", "lost"], help_text="The filter applied.")
    count = serializers.IntegerField(help_text="Rating changes that match the filters.")
    history = RatingChangeSerializer(many=True)
