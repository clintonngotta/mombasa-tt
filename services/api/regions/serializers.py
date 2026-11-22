from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from competitions.models import Tournament
from organizations.access import jurisdiction
from organizations.models import Organization

from .models import AgendaItem, Article, Meeting, MeetingInvitee, MeetingPenalty, Sponsorship


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
    """A regional or national body as anyone signed in may see it."""

    class Meta:
        model = Organization
        fields = ["id", "name", "kind", "town", "country", "region"]
        read_only_fields = fields


class RegionalBodyInputSerializer(serializers.Serializer):
    """A platform super admin creates a body (TASK-107): a regional body for one catalogue region of the
    country, or the national body for the country, and names its first admin by their account's email."""

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    kind = serializers.ChoiceField(
        choices=[Organization.Kind.REGIONAL_BODY, Organization.Kind.NATIONAL_BODY],
        default=Organization.Kind.REGIONAL_BODY,
    )
    country = serializers.CharField(max_length=2, min_length=2)
    region = serializers.CharField(max_length=100, trim_whitespace=True, required=False, allow_blank=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True, required=False, allow_blank=True)
    admin_email = serializers.EmailField(max_length=254)

    def validate(self, attrs):
        if attrs["kind"] == Organization.Kind.REGIONAL_BODY and not attrs.get("region"):
            raise serializers.ValidationError({"region": "Choose the region the body is for."})
        if attrs["kind"] == Organization.Kind.NATIONAL_BODY and attrs.get("region"):
            raise serializers.ValidationError({"region": "A national body is for the whole country."})
        attrs["country"] = attrs["country"].upper()
        return attrs


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
                    organization__in=Organization.objects.filter(jurisdiction(body)),
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


PENALIZED = [
    MeetingInvitee.Attendance.ABSENT,
    MeetingInvitee.Attendance.LATE,
    MeetingInvitee.Attendance.APOLOGIES,
]
MARKS = [MeetingInvitee.Attendance.PRESENT, *PENALIZED]


class RuleSerializer(serializers.Serializer):
    """What missing the meeting costs: one rule each for absent, late and apologies."""

    applies_to = serializers.ChoiceField(choices=PENALIZED)
    penalty = serializers.CharField(max_length=200, trim_whitespace=True)
    amount_minor = serializers.IntegerField(
        min_value=1,
        max_value=100_000_000,
        required=False,
        allow_null=True,
        default=None,
        help_text="A fine in the smallest unit of KES, when the penalty is one.",
    )


class SecretarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class PenaltyChangeSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    by_name = serializers.CharField()
    changes = serializers.DictField(child=serializers.ListField(allow_null=True))


class PenaltySerializer(serializers.ModelSerializer):
    applies_to = serializers.ChoiceField(choices=PENALIZED, read_only=True)
    issued_by_name = serializers.CharField(
        source="issued_by.display_name", read_only=True, allow_null=True, default=None
    )
    history = PenaltyChangeSerializer(many=True, read_only=True)

    class Meta:
        model = MeetingPenalty
        fields = [
            "id",
            "applies_to",
            "penalty",
            "amount_minor",
            "currency",
            "status",
            "note",
            "issued_by_name",
            "issued_at",
            "updated_at",
            "history",
        ]
        read_only_fields = fields


class PenaltyUpdateSerializer(serializers.Serializer):
    penalty = serializers.CharField(max_length=200, trim_whitespace=True, required=False)
    amount_minor = serializers.IntegerField(
        min_value=1, max_value=100_000_000, required=False, allow_null=True
    )
    status = serializers.ChoiceField(choices=MeetingPenalty.Status.choices, required=False)
    note = serializers.CharField(max_length=300, trim_whitespace=True, allow_blank=True, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Change the penalty, amount, status or note.")
        return attrs


class AttendanceSerializer(serializers.Serializer):
    invitee = serializers.UUIDField()
    attendance = serializers.ChoiceField(choices=MARKS)


class InviteeSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    club = serializers.CharField(source="club.name", read_only=True, allow_null=True, default=None)
    penalty = serializers.SerializerMethodField()

    class Meta:
        model = MeetingInvitee
        fields = [
            "id",
            "display_name",
            "club",
            "answer",
            "checked_in_at",
            "attendance",
            "marked_at",
            "penalty",
        ]
        read_only_fields = fields

    @extend_schema_field(PenaltySerializer(allow_null=True))
    def get_penalty(self, invitee) -> dict | None:
        try:
            return PenaltySerializer(invitee.penalty).data
        except MeetingPenalty.DoesNotExist:
            return None


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
    rules = RuleSerializer(many=True, required=False)
    secretary = SecretarySerializer(read_only=True, allow_null=True)
    secretary_id = serializers.UUIDField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="An active member of the host. Defaults to whoever calls the meeting.",
    )
    invitees = serializers.SerializerMethodField()
    me = serializers.SerializerMethodField()
    can_take_attendance = serializers.SerializerMethodField(
        help_text="You may mark attendance and issue penalties: governance staff or the secretary."
    )
    can_edit_penalties = serializers.SerializerMethodField(
        help_text="You may change issued penalties: the host's admin or a platform super admin."
    )

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
            "rules",
            "secretary",
            "secretary_id",
            "status",
            "minutes",
            "minutes_recorded_at",
            "cancel_reason",
            "published_at",
            "invitees",
            "me",
            "can_take_attendance",
            "can_edit_penalties",
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
            "can_take_attendance",
            "can_edit_penalties",
        ]

    def _takes_attendance(self, meeting) -> bool:
        user = self.context["request"].user
        return bool(self.context.get("staff")) or (
            meeting.secretary_id is not None and meeting.secretary_id == user.pk
        )

    @extend_schema_field(InviteeSerializer(many=True))
    def get_invitees(self, meeting) -> list[dict]:
        if not self._takes_attendance(meeting):
            return []
        invitees = meeting.invitees.select_related("user", "club", "penalty__issued_by")
        return InviteeSerializer(invitees, many=True).data

    def get_can_take_attendance(self, meeting) -> bool:
        return self._takes_attendance(meeting)

    def get_can_edit_penalties(self, meeting) -> bool:
        return bool(self.context.get("top"))

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
        if audience == Meeting.Audience.CLUB_ADMINS and not self.context["organization"].is_body:
            raise serializers.ValidationError(
                {"audience": "Only a governing body invites its clubs' admins."}
            )
        if len(attrs.get("agenda", [])) > 30:
            raise serializers.ValidationError({"agenda": "Keep the agenda to 30 items."})
        rules = attrs.get("rules", [])
        if len({rule["applies_to"] for rule in rules}) != len(rules):
            raise serializers.ValidationError(
                {"rules": "Give at most one rule each for absent, late and apologies."}
            )
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
