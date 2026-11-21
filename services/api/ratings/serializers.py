from rest_framework import serializers

from attachments.serializers import AttachmentLinkSerializer

from .models import Discipline


class RankingRowSerializer(serializers.Serializer):
    rank = serializers.IntegerField(help_text="Players with the same rating share a rank.")
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    clubs = serializers.ListField(child=serializers.CharField())
    listed = serializers.BooleanField(
        help_text="The viewer can open the player's page: a listed player's, or signed out anyone's."
    )
    is_me = serializers.BooleanField()
    avatar = AttachmentLinkSerializer(
        allow_null=True, help_text="The player's photo: only for listed players and yourself."
    )
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


class ClubRankingRowSerializer(serializers.Serializer):
    rank = serializers.IntegerField(help_text="Clubs with the same total share a rank.")
    organization_id = serializers.UUIDField()
    name = serializers.CharField()
    town = serializers.CharField(allow_blank=True)
    total_points = serializers.FloatField(help_text="Sum of current ratings of active rated members.")
    rated_members = serializers.IntegerField()


class ClubRankingSerializer(serializers.Serializer):
    discipline = serializers.ChoiceField(choices=Discipline.choices)
    processing = serializers.BooleanField()
    rows = ClubRankingRowSerializer(many=True)


class GeographyRankingRowSerializer(serializers.Serializer):
    rank = serializers.IntegerField()
    country = serializers.CharField()
    region = serializers.CharField(allow_blank=True)
    city = serializers.CharField(allow_blank=True)
    total_points = serializers.FloatField()
    rated_players = serializers.IntegerField()


class GeographyRankingSerializer(serializers.Serializer):
    discipline = serializers.ChoiceField(choices=Discipline.choices)
    level = serializers.ChoiceField(choices=["country", "region", "city"])
    processing = serializers.BooleanField()
    rows = GeographyRankingRowSerializer(many=True)


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
    timezone = serializers.CharField(help_text="The tournament's time zone, to show `at` in.")


class PlayerRatingsSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    avatar = AttachmentLinkSerializer(
        allow_null=True, help_text="The player's photo: only for listed players and yourself."
    )
    processing = serializers.BooleanField()
    summaries = RatingSummarySerializer(many=True)
    discipline = serializers.ChoiceField(choices=Discipline.choices, help_text="The one `history` is of.")
    result = serializers.ChoiceField(choices=["all", "won", "lost"], help_text="The filter applied.")
    count = serializers.IntegerField(help_text="Rating changes that match the filters.")
    history = RatingChangeSerializer(many=True)
