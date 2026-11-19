from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from competitions.models import Tournament
from organizations.models import Organization

from .models import AgendaItem, Article, Meeting, MeetingInvitee, Sponsorship


class OrgRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    town = serializers.CharField()


class TournamentRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    status = serializers.CharField()


class RegionalBodySerializer(serializers.ModelSerializer):
    """A regional body as anyone signed in may see it."""

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "country", "region"]
        read_only_fields = fields


class RegionalBodyInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    region_id = serializers.IntegerField(required=False)
    town = serializers.CharField(max_length=80, trim_whitespace=True, required=False, allow_blank=True)


class RegionClubSerializer(serializers.ModelSerializer):
    members = serializers.IntegerField(read_only=True)
    upcoming_tournaments = serializers.IntegerField(read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "kind", "members", "upcoming_tournaments"]
        read_only_fields = fields


class AgendaItemSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(
        max_length=1000, trim_whitespace=True, allow_blank=True, required=False
    )
    tournament = TournamentRefSerializer(read_only=True, allow_null=True)
    tournament_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    organization = OrgRefSerializer(read_only=True)

    class Meta:
        model = AgendaItem
        fields = [
            "id",
            "organization",
            "kind",
            "title",
            "description",
            "starts_on",
            "ends_on",
            "tournament",
            "tournament_id",
        ]
        read_only_fields = ["id", "organization", "tournament"]
        extra_kwargs = {"ends_on": {"required": False}}

    def validate(self, attrs):
        starts = attrs.get("starts_on", self.instance.starts_on if self.instance else None)
        ends = attrs.get("ends_on") or (
            self.instance.ends_on if self.instance and "starts_on" not in attrs else starts
        )
        if ends and starts and ends < starts:
            raise serializers.ValidationError({"ends_on": "It ends before it starts."})
        attrs["ends_on"] = ends
        if attrs.get("tournament_id"):
            body = self.context["organization"]
            tournament = (
                Tournament.objects.filter(
                    pk=attrs["tournament_id"],
                    organization__country=body.country,
                    organization__region__iexact=body.region,
                )
                .exclude(status=Tournament.Status.DRAFT)
                .first()
            )
            if tournament is None:
                raise serializers.ValidationError(
                    {"tournament_id": "Choose a published tournament in the region."}
                )
            attrs["tournament"] = tournament
        elif "tournament_id" in attrs:
            attrs["tournament"] = None
        attrs.pop("tournament_id", None)
        return attrs


class ArticleSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=140, trim_whitespace=True)
    summary = serializers.CharField(max_length=280, trim_whitespace=True, allow_blank=True, required=False)
    body = serializers.CharField(max_length=10000, trim_whitespace=True)
    organization = OrgRefSerializer(read_only=True)
    clubs = OrgRefSerializer(many=True, read_only=True)
    club_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, max_length=200
    )

    class Meta:
        model = Article
        fields = [
            "id",
            "organization",
            "title",
            "summary",
            "body",
            "audience",
            "clubs",
            "club_ids",
            "status",
            "published_at",
            "updated_at",
        ]
        read_only_fields = ["id", "organization", "clubs", "status", "published_at", "updated_at"]


class AgendaRowSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, trim_whitespace=True)
    presenter = serializers.CharField(
        max_length=120, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    tournament = serializers.UUIDField(required=False, allow_null=True, default=None)


class InviteeSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    club = serializers.CharField(source="club.name", read_only=True, allow_null=True, default=None)

    class Meta:
        model = MeetingInvitee
        fields = ["id", "display_name", "club", "answer", "checked_in_at"]
        read_only_fields = fields


class MeetingSerializer(serializers.ModelSerializer):
    """A meeting. Invitees (names only), answers and attendance are for the host's governance staff;
    an invitee sees their own answer as `me`."""

    title = serializers.CharField(max_length=120, trim_whitespace=True)
    location = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=True, required=False)
    organization = OrgRefSerializer(read_only=True)
    agenda = AgendaRowSerializer(many=True, required=False)
    named_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, max_length=200
    )
    invitees = serializers.SerializerMethodField()
    me = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            "id",
            "organization",
            "title",
            "kind",
            "starts_at",
            "ends_at",
            "location",
            "online_link",
            "audience",
            "named_ids",
            "agenda",
            "status",
            "minutes",
            "minutes_recorded_at",
            "cancel_reason",
            "published_at",
            "invitees",
            "me",
        ]
        read_only_fields = [
            "id",
            "organization",
            "status",
            "minutes",
            "minutes_recorded_at",
            "cancel_reason",
            "published_at",
            "invitees",
            "me",
        ]

    @extend_schema_field(InviteeSerializer(many=True))
    def get_invitees(self, meeting) -> list[dict]:
        if not self.context.get("staff"):
            return []
        return InviteeSerializer(meeting.invitees.select_related("user", "club"), many=True).data

    @extend_schema_field(InviteeSerializer(allow_null=True))
    def get_me(self, meeting) -> dict | None:
        user = self.context["request"].user
        mine = next((i for i in meeting.invitees.all() if i.user_id == user.pk), None)
        return InviteeSerializer(mine).data if mine else None

    def validate(self, attrs):
        starts = attrs.get("starts_at", self.instance.starts_at if self.instance else None)
        ends = attrs.get("ends_at", self.instance.ends_at if self.instance else None)
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "The meeting ends before it starts."})
        audience = attrs.get(
            "audience", self.instance.audience if self.instance else Meeting.Audience.COMMITTEE
        )
        if (
            audience == Meeting.Audience.CLUB_ADMINS
            and self.context["organization"].kind != Organization.Kind.REGIONAL_BODY
        ):
            raise serializers.ValidationError({"audience": "Only a regional body invites its clubs' admins."})
        if len(attrs.get("agenda", [])) > 30:
            raise serializers.ValidationError({"agenda": "Keep the agenda to 30 items."})
        return attrs


class AnswerSerializer(serializers.Serializer):
    answer = serializers.ChoiceField(
        choices=[MeetingInvitee.Answer.ATTENDING, MeetingInvitee.Answer.APOLOGIES]
    )


class MinutesSerializer(serializers.Serializer):
    minutes = serializers.CharField(max_length=20000, trim_whitespace=True)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class InKindSerializer(serializers.Serializer):
    item = serializers.CharField(max_length=80, trim_whitespace=True)
    quantity = serializers.IntegerField(min_value=1, max_value=100000)


class SponsorshipSerializer(serializers.ModelSerializer):
    sponsor = OrgRefSerializer(read_only=True)
    tournament = TournamentRefSerializer(read_only=True)
    tournament_id = serializers.UUIDField(write_only=True)
    in_kind = InKindSerializer(many=True, required=False)
    conditions = serializers.CharField(
        max_length=1000, trim_whitespace=True, allow_blank=True, required=False
    )

    class Meta:
        model = Sponsorship
        fields = [
            "id",
            "sponsor",
            "tournament",
            "tournament_id",
            "amount_minor",
            "currency",
            "in_kind",
            "conditions",
            "status",
            "reason",
            "decided_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "sponsor",
            "tournament",
            "currency",
            "status",
            "reason",
            "decided_at",
            "created_at",
        ]

    def validate(self, attrs):
        if not attrs.get("amount_minor") and not attrs.get("in_kind"):
            raise serializers.ValidationError({"amount_minor": "Offer an amount, goods, or both."})
        if len(attrs.get("in_kind", [])) > 20:
            raise serializers.ValidationError({"in_kind": "List at most 20 items."})
        return attrs


class SponsorSerializer(serializers.ModelSerializer):
    """An accepted sponsorship as everyone who sees the tournament sees it."""

    sponsor = OrgRefSerializer(read_only=True)
    in_kind = InKindSerializer(many=True, read_only=True)

    class Meta:
        model = Sponsorship
        fields = ["id", "sponsor", "amount_minor", "currency", "in_kind"]
        read_only_fields = fields


class DecisionSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=300, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
