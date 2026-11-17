from zoneinfo import ZoneInfo

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from core.money import MAX_AMOUNT_MINOR
from core.timezones import validate_timezone
from facilities.models import Venue
from facilities.serializers import VenueSummarySerializer
from organizations.models import Organization

from .models import MAX_TEAM_ROSTER, Entry, EntryPlayer, Event, LifecycleEntry, Tournament

BEST_OF = (3, 5, 7)
MAX_CAPACITY = 512
MAX_REST_MINUTES = 240
MAX_GROUPS = 64
MAX_QUALIFIERS = 8


@extend_schema_serializer(component_name="Money")
class EntryFeeSerializer(serializers.Serializer):
    """The event's declared entry fee in the REQ-032 money shape."""

    amount_minor = serializers.IntegerField(source="entry_fee_minor", min_value=0, max_value=MAX_AMOUNT_MINOR)
    currency = serializers.RegexField(r"^[A-Z]{3}$", source="entry_fee_currency", default="KES")


class EventSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    entry_fee = EntryFeeSerializer(source="*", required=False)
    capacity = serializers.IntegerField(min_value=2, max_value=MAX_CAPACITY, allow_null=True, required=False)
    best_of = serializers.ChoiceField(choices=BEST_OF, required=False)
    rest_minutes = serializers.IntegerField(min_value=0, max_value=MAX_REST_MINUTES, required=False)
    group_count = serializers.IntegerField(min_value=2, max_value=MAX_GROUPS, allow_null=True, required=False)
    qualifiers_per_group = serializers.IntegerField(
        min_value=1, max_value=MAX_QUALIFIERS, allow_null=True, required=False
    )
    accepted_count = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "name",
            "kind",
            "format",
            "capacity",
            "best_of",
            "rest_minutes",
            "registration_opens_at",
            "registration_closes_at",
            "entry_fee",
            "seeding",
            "group_count",
            "qualifiers_per_group",
            "accepted_count",
            "status",
            "revision",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]
        read_only_fields = [
            "id",
            "status",
            "revision",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]

    def get_accepted_count(self, event) -> int:
        """Entries holding a place. Counted here when the caller didn't annotate it."""
        counted = getattr(event, "accepted_count", None)
        return event.entries.filter(status=Entry.Status.ACCEPTED).count() if counted is None else counted

    def validate(self, attrs):
        def current(name):
            return attrs[name] if name in attrs else getattr(self.instance, name, None)

        # What the caller asked to change in the structure, before the clean-up below can hide it.
        self.structure_changes = {
            name
            for name in Event.STRUCTURE_FIELDS
            if self.instance is not None and name in attrs and attrs[name] != getattr(self.instance, name)
        }

        if current("format") == Event.Format.GROUPS_KNOCKOUT:
            groups, qualifiers, capacity = (
                current("group_count"),
                current("qualifiers_per_group"),
                current("capacity"),
            )
            errors = {}
            if groups is None:
                errors["group_count"] = "Say how many groups there are."
            if qualifiers is None:
                errors["qualifiers_per_group"] = "Say how many from each group go through."
            if errors:
                raise serializers.ValidationError(errors)
            # Every group needs at least one entry more than the number that qualify from it.
            if capacity is not None and capacity < groups * (qualifiers + 1):
                raise serializers.ValidationError(
                    {
                        "capacity": f"{groups} groups sending {qualifiers} through need at least "
                        f"{groups * (qualifiers + 1)} entries."
                    }
                )
        else:
            # Groups and qualifiers only mean something for groups followed by a knockout.
            attrs["group_count"] = None
            attrs["qualifiers_per_group"] = None

        opens, closes = current("registration_opens_at"), current("registration_closes_at")
        if opens and closes and closes <= opens:
            raise serializers.ValidationError(
                {"registration_closes_at": "Registration must close after it opens."}
            )
        tournament = self.context.get("tournament") or getattr(self.instance, "tournament", None)
        if (
            closes
            and tournament
            and closes.astimezone(ZoneInfo(tournament.timezone)).date() > tournament.ends_on
        ):
            raise serializers.ValidationError(
                {"registration_closes_at": "Registration must close by the tournament's last day."}
            )
        return attrs


class OrganizationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "town"]
        read_only_fields = fields


class TournamentSerializer(serializers.ModelSerializer):
    """A tournament with its events. The same fields serve staff and the public (REQ-020): nothing here
    is private once the tournament is published, and drafts are served to the host's staff only."""

    name = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(
        max_length=2000, trim_whitespace=True, allow_blank=True, required=False
    )
    organization = OrganizationSummarySerializer(read_only=True)
    venue = VenueSummarySerializer(read_only=True, allow_null=True)
    venue_id = serializers.PrimaryKeyRelatedField(
        source="venue", queryset=Venue.objects.all(), write_only=True, allow_null=True, required=False
    )
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])
    events = EventSerializer(many=True, read_only=True)

    class Meta:
        model = Tournament
        fields = [
            "id",
            "organization",
            "venue",
            "venue_id",
            "name",
            "description",
            "starts_on",
            "ends_on",
            "timezone",
            "status",
            "published_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
            "events",
        ]
        read_only_fields = [
            "id",
            "status",
            "published_at",
            "started_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
        ]

    def validate_venue_id(self, venue):
        """The venue must be one of the host's own and in use (a tournament may keep the one it has)."""
        if venue is None:
            if self.instance is not None and self.instance.status != Tournament.Status.DRAFT:
                raise serializers.ValidationError("A published tournament keeps a venue.")
            return venue
        unchanged = self.instance is not None and self.instance.venue_id == venue.id
        organization = self.context["organization"]
        if venue.organization_id != organization.id or not (venue.active or unchanged):
            raise serializers.ValidationError("Choose one of this organization's venues.")
        return venue

    def validate(self, attrs):
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "The last day can't be before the first day."})
        return attrs


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class LifecycleEntrySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default="")

    class Meta:
        model = LifecycleEntry
        fields = ["id", "action", "event_name", "actor_name", "reason", "snapshot", "created_at"]
        read_only_fields = fields


class EntryPlayerSerializer(serializers.ModelSerializer):
    """A player in an entry: the name they play under, nothing else (REQ-020)."""

    id = serializers.UUIDField(source="user_id", read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = EntryPlayer
        fields = ["id", "display_name"]
        read_only_fields = fields


class EntrySerializer(serializers.ModelSerializer):
    """An entry as its players, staff and (once accepted) everybody else see it. Deliberately nothing
    about payment: accepted means a place in the event, not a paid fee (REQ-008)."""

    players = EntryPlayerSerializer(many=True, read_only=True)
    captain_id = serializers.UUIDField(read_only=True, allow_null=True)
    mine = serializers.SerializerMethodField()

    class Meta:
        model = Entry
        fields = [
            "id",
            "status",
            "players",
            "team_name",
            "captain_id",
            "reason",
            "created_at",
            "decided_at",
            "withdrawn_at",
            "checked_in_at",
            "mine",
        ]
        read_only_fields = fields

    def get_mine(self, entry) -> bool:
        """Whether the caller plays in it, so may withdraw it."""
        user = self.context["request"].user
        return any(place.user_id == user.id for place in entry.players.all())


class EntryEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ["id", "name", "kind", "status"]
        read_only_fields = fields


class EntryTournamentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tournament
        fields = ["id", "name", "starts_on", "ends_on", "timezone", "status"]
        read_only_fields = fields


class MyEntrySerializer(EntrySerializer):
    """One of the caller's own entries, with the event and tournament it is for."""

    event = EntryEventSerializer(read_only=True)
    tournament = EntryTournamentSerializer(source="event.tournament", read_only=True)

    class Meta(EntrySerializer.Meta):
        fields = [*EntrySerializer.Meta.fields, "event", "tournament"]
        read_only_fields = fields


class EntryRequestSerializer(serializers.Serializer):
    """Who is entering. Left out, `player_ids` is the caller alone and `captain_id` the caller."""

    player_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_TEAM_ROSTER, required=False
    )
    team_name = serializers.CharField(max_length=80, trim_whitespace=True, allow_blank=True, required=False)
    captain_id = serializers.UUIDField(allow_null=True, required=False)

    def validate_player_ids(self, ids):
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Each player can be in the entry once.")
        return ids


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, trim_whitespace=True, allow_blank=True, required=False)
