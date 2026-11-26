import uuid

from django.db.models import Q
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from attachments.serializers import AttachmentLinkSerializer
from competitions.models import Tournament
from organizations.access import jurisdiction
from organizations.models import Organization

from .models import (
    ActionItem,
    AgendaItem,
    Article,
    Meeting,
    MeetingDocument,
    MeetingInvitee,
    MeetingPenalty,
    MinutesAmendment,
    Sponsorship,
)


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


ITEM_ID = r"^[0-9a-f]{12}$"


class AgendaRowSerializer(serializers.Serializer):
    id = serializers.RegexField(
        ITEM_ID,
        required=False,
        help_text="Given by the API. Send it back when changing the agenda so the item keeps its "
        "documents, decisions and action items; leave it out for a new item.",
    )
    title = serializers.CharField(max_length=200, trim_whitespace=True)
    presenter = serializers.CharField(
        max_length=120, trim_whitespace=True, allow_blank=True, required=False, default=""
    )
    tournament = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="A tournament the item is about: one of the host's, or any published one.",
    )
    tournament_name = serializers.CharField(read_only=True, allow_null=True, default=None)


class StrictSerializer(serializers.Serializer):
    """Refuses fields it doesn't know, so a misspelt or smuggled field is an error, not silence."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", {}) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class MeetingDocumentSerializer(serializers.ModelSerializer):
    """A document of a meeting with a fresh signed link to the PDF."""

    file = serializers.SerializerMethodField()

    class Meta:
        model = MeetingDocument
        fields = ["id", "item", "title", "file", "created_at"]
        read_only_fields = fields

    @extend_schema_field(AttachmentLinkSerializer)
    def get_file(self, document) -> dict:
        return AttachmentLinkSerializer(document.file_id).data


class MeetingDocumentUploadSerializer(StrictSerializer):
    title = serializers.CharField(max_length=120, trim_whitespace=True)
    item = serializers.RegexField(ITEM_ID, required=False, allow_blank=True, default="")
    file = serializers.FileField()


class DecisionRowSerializer(serializers.Serializer):
    item = serializers.RegexField(ITEM_ID, required=False, allow_blank=True, default="")
    text = serializers.CharField(max_length=1000, trim_whitespace=True)


class ActionItemSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(
        source="owner.display_name", read_only=True, allow_null=True, default=None
    )
    mine = serializers.SerializerMethodField(help_text="You own it, so you may mark it done.")
    owner_id = serializers.SerializerMethodField(
        help_text="For whoever writes the minutes, to change who it is given to; null for everyone else."
    )

    class Meta:
        model = ActionItem
        fields = [
            "id",
            "item",
            "description",
            "owner_name",
            "owner_id",
            "mine",
            "due_on",
            "status",
            "done_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_owner_id(self, action):
        return str(action.owner_id) if action.owner_id and self.context.get("writer") else None

    def get_mine(self, action) -> bool:
        return action.owner_id is not None and action.owner_id == self.context["request"].user.pk


class MyActionItemSerializer(ActionItemSerializer):
    """One of your action items with the meeting it came from."""

    meeting = serializers.UUIDField(source="meeting_id", read_only=True)
    meeting_title = serializers.CharField(source="meeting.title", read_only=True)
    organization = OrgRefSerializer(source="meeting.organization", read_only=True)

    class Meta(ActionItemSerializer.Meta):
        fields = [*ActionItemSerializer.Meta.fields, "meeting", "meeting_title", "organization"]
        read_only_fields = fields


class ActionItemInputSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, help_text="An item already recorded; leave out for a new one.")
    item = serializers.RegexField(ITEM_ID, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=300, trim_whitespace=True)
    owner_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        default=None,
        help_text="The invitee or member of the host who will do it.",
    )
    due_on = serializers.DateField(required=False, allow_null=True, default=None)


class ActionItemStatusSerializer(StrictSerializer):
    status = serializers.ChoiceField(choices=ActionItem.Status.choices)


class AmendmentSerializer(serializers.ModelSerializer):
    by_name = serializers.CharField(
        source="created_by.display_name", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = MinutesAmendment
        fields = ["id", "text", "by_name", "created_at"]
        read_only_fields = fields


class AmendmentInputSerializer(StrictSerializer):
    text = serializers.CharField(max_length=5000, trim_whitespace=True)


class ApproveMinutesSerializer(StrictSerializer):
    create_next = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Also create the next meeting as a draft on the date the minutes give.",
    )


class OwnerChoiceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


def agenda_with_ids(rows: list[dict]) -> list[dict]:
    """The agenda as stored: each item with its id (a new one where none was sent)."""
    seen, stored = set(), []
    for row in rows:
        key = row.get("id")
        if not key or key in seen:
            key = uuid.uuid4().hex[:12]
        seen.add(key)
        tournament = row.get("tournament")
        stored.append(
            {
                "id": key,
                "title": row["title"],
                "presenter": row.get("presenter", ""),
                "tournament": str(tournament) if tournament else None,
            }
        )
    return stored


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
            "apology_reason",
            "apologised_at",
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
    documents = MeetingDocumentSerializer(many=True, read_only=True)
    decisions = serializers.SerializerMethodField()
    action_items = serializers.SerializerMethodField()
    amendments = serializers.SerializerMethodField()
    minutes = serializers.SerializerMethodField(
        help_text="A draft is for governance staff and the secretary; invitees read approved minutes."
    )
    minutes_status = serializers.SerializerMethodField()
    next_meeting_at = serializers.SerializerMethodField()
    next_meeting = serializers.SerializerMethodField(
        help_text="The draft created from these minutes, for governance staff."
    )
    owner_choices = serializers.SerializerMethodField(
        help_text="Who an action item can be given to, for whoever writes the minutes: names only."
    )
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
            "revision",
            "documents",
            "minutes",
            "minutes_status",
            "minutes_recorded_at",
            "minutes_approved_at",
            "decisions",
            "action_items",
            "amendments",
            "next_meeting_at",
            "next_meeting",
            "owner_choices",
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
            "revision",
            "documents",
            "minutes",
            "minutes_status",
            "minutes_recorded_at",
            "minutes_approved_at",
            "decisions",
            "action_items",
            "amendments",
            "next_meeting_at",
            "next_meeting",
            "owner_choices",
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

    def _reads_minutes(self, meeting) -> bool:
        """Approved minutes are for everyone who sees the meeting; a draft for whoever writes it."""
        return meeting.minutes_status == Meeting.MinutesStatus.APPROVED or self._takes_attendance(meeting)

    def get_minutes(self, meeting) -> str:
        return meeting.minutes if self._reads_minutes(meeting) else ""

    @extend_schema_field(serializers.ChoiceField(choices=Meeting.MinutesStatus.choices))
    def get_minutes_status(self, meeting) -> str:
        return meeting.minutes_status if self._reads_minutes(meeting) else ""

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_next_meeting_at(self, meeting):
        if not self._reads_minutes(meeting) or meeting.next_meeting_at is None:
            return None
        return serializers.DateTimeField().to_representation(meeting.next_meeting_at)

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_next_meeting(self, meeting):
        if not self.context.get("staff"):
            return None
        following = getattr(meeting, "next_meeting", None)
        return str(following.pk) if following else None

    @extend_schema_field(DecisionRowSerializer(many=True))
    def get_decisions(self, meeting) -> list[dict]:
        return meeting.decisions if self._reads_minutes(meeting) else []

    @extend_schema_field(ActionItemSerializer(many=True))
    def get_action_items(self, meeting) -> list[dict]:
        if not self._reads_minutes(meeting):
            return []
        context = {**self.context, "writer": self._takes_attendance(meeting)}
        return ActionItemSerializer(meeting.action_items.all(), many=True, context=context).data

    @extend_schema_field(AmendmentSerializer(many=True))
    def get_amendments(self, meeting) -> list[dict]:
        if not self._reads_minutes(meeting):
            return []
        return AmendmentSerializer(meeting.amendments.all(), many=True).data

    @extend_schema_field(OwnerChoiceSerializer(many=True))
    def get_owner_choices(self, meeting) -> list[dict]:
        if not self.context.get("detail") or not self._takes_attendance(meeting):
            return []
        from .minutes import owner_choices

        return [{"id": pk, "display_name": name} for pk, name in owner_choices(meeting).items()]

    def to_representation(self, meeting):
        data = super().to_representation(meeting)
        names = self.context.get("tournament_names", {})
        data["agenda"] = [
            {**row, "id": row.get("id", ""), "tournament_name": names.get(row.get("tournament"))}
            for row in meeting.agenda
        ]
        return data

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
        host = self.context["organization"]
        if audience == Meeting.Audience.CLUB_ADMINS and not host.is_body:
            raise serializers.ValidationError(
                {"audience": "Only a governing body invites its clubs' admins."}
            )
        if audience == Meeting.Audience.REPRESENTATIVES and not host.is_body:
            raise serializers.ValidationError(
                {"audience": "Only a governing body invites its representatives."}
            )
        if len(attrs.get("agenda", [])) > 30:
            raise serializers.ValidationError({"agenda": "Keep the agenda to 30 items."})
        if "agenda" in attrs:
            linked = {row["tournament"] for row in attrs["agenda"] if row.get("tournament")}
            known = set(
                Tournament.objects.filter(pk__in=linked)
                .filter(Q(organization=host) | ~Q(status=Tournament.Status.DRAFT))
                .values_list("pk", flat=True)
            )
            if linked - known:
                raise serializers.ValidationError(
                    {"agenda": "Link an item to one of your tournaments or a published one."}
                )
            attrs["agenda"] = agenda_with_ids(attrs["agenda"])
        rules = attrs.get("rules", [])
        if len({rule["applies_to"] for rule in rules}) != len(rules):
            raise serializers.ValidationError(
                {"rules": "Give at most one rule each for absent, late and apologies."}
            )
        return attrs


class AnswerSerializer(StrictSerializer):
    answer = serializers.ChoiceField(
        choices=[MeetingInvitee.Answer.ATTENDING, MeetingInvitee.Answer.APOLOGIES]
    )
    reason = serializers.CharField(
        max_length=300,
        trim_whitespace=True,
        allow_blank=True,
        required=False,
        default="",
        help_text="With apologies: why, for whoever takes attendance.",
    )


class MinutesSerializer(StrictSerializer):
    """The minutes as a draft: the text, what was decided, who does what, and the next meeting's date."""

    minutes = serializers.CharField(max_length=20000, trim_whitespace=True, allow_blank=True, default="")
    decisions = DecisionRowSerializer(many=True, required=False, max_length=60)
    action_items = ActionItemInputSerializer(many=True, required=False, max_length=60)
    next_meeting_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not (attrs["minutes"] or attrs.get("decisions") or attrs.get("action_items")):
            raise serializers.ValidationError({"minutes": "Write the minutes, a decision or an action item."})
        return attrs


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
