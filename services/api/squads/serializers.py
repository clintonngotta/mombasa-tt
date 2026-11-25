import uuid

from rest_framework import serializers

from events.models import ExternalEvent
from ratings.models import Discipline

from .models import Squad, SquadPlace

SLOT_ID = r"^[0-9a-f]{12}$"
MAX_SLOTS = 12
MAX_PLACES = 30


class StrictSquadFields(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", None) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class SquadSlotSerializer(serializers.Serializer):
    id = serializers.RegexField(
        SLOT_ID, required=False, help_text="Given by the API; send it back to keep the slot."
    )
    label = serializers.CharField(max_length=60, trim_whitespace=True)
    places = serializers.IntegerField(min_value=1, max_value=MAX_PLACES)


class SquadPlaceSerializer(serializers.ModelSerializer):
    """A picked player as the squad's staff see them: a name, their club for a region's squad, the slot,
    their answer and why they were picked outside the rotation."""

    user_id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    club = serializers.CharField(source="club.name", read_only=True, allow_null=True, default=None)

    class Meta:
        model = SquadPlace
        fields = [
            "id",
            "user_id",
            "display_name",
            "club",
            "slot",
            "status",
            "recommended",
            "override_reason",
            "picked_at",
            "responded_at",
        ]
        read_only_fields = fields


class SquadSerializer(serializers.ModelSerializer):
    """A squad for the organization's competition staff."""

    title = serializers.CharField(max_length=120, trim_whitespace=True)
    notes = serializers.CharField(max_length=1000, trim_whitespace=True, allow_blank=True, required=False)
    discipline = serializers.ChoiceField(choices=Discipline.choices, required=False)
    slots = SquadSlotSerializer(many=True, max_length=MAX_SLOTS)
    external_event_id = serializers.UUIDField(required=False, allow_null=True)
    places = SquadPlaceSerializer(many=True, read_only=True)

    class Meta:
        model = Squad
        fields = [
            "id",
            "title",
            "external_event_id",
            "starts_on",
            "ends_on",
            "discipline",
            "notes",
            "slots",
            "status",
            "places",
            "published_at",
        ]
        read_only_fields = ["id", "status", "places", "published_at"]

    def validate_external_event_id(self, value):
        if value is None:
            return None
        if not ExternalEvent.objects.filter(pk=value, review=ExternalEvent.Review.APPROVED).exists():
            raise serializers.ValidationError("Choose a listed event.")
        return value

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        starts = attrs.get("starts_on", getattr(self.instance, "starts_on", None))
        ends = attrs.get("ends_on", getattr(self.instance, "ends_on", None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError({"ends_on": "It ends before it starts."})
        if "slots" in attrs:
            if not attrs["slots"]:
                raise serializers.ValidationError({"slots": "Add at least one slot."})
            seen, stored = set(), []
            for slot in attrs["slots"]:
                key = slot.get("id")
                if not key or key in seen:
                    key = uuid.uuid4().hex[:12]
                seen.add(key)
                stored.append({"id": key, "label": slot["label"], "places": slot["places"]})
            attrs["slots"] = stored
        return attrs


class PickSerializer(StrictSquadFields):
    user_id = serializers.UUIDField()
    slot = serializers.RegexField(SLOT_ID)
    reason = serializers.CharField(
        max_length=300,
        trim_whitespace=True,
        allow_blank=True,
        required=False,
        default="",
        help_text="Needed when the rotation puts other players first.",
    )


class SquadCandidateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    club = serializers.CharField(allow_null=True)
    last_represented_on = serializers.DateField(allow_null=True)
    in_previous_squad = serializers.BooleanField()
    rating = serializers.IntegerField()


class SquadRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()


class SquadHostSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MySquadPlaceSerializer(serializers.ModelSerializer):
    """A player's own place: the squad, the slot, their answer, and who else is going by name."""

    squad = SquadRefSerializer(read_only=True)
    organization = SquadHostSerializer(source="squad.organization", read_only=True)
    slot_label = serializers.SerializerMethodField()
    notes = serializers.CharField(source="squad.notes", read_only=True)
    teammates = serializers.SerializerMethodField(help_text="The others who accepted, by display name.")

    class Meta:
        model = SquadPlace
        fields = ["id", "squad", "organization", "slot_label", "notes", "status", "responded_at", "teammates"]
        read_only_fields = fields

    def get_slot_label(self, place) -> str:
        return next((slot["label"] for slot in place.squad.slots if slot["id"] == place.slot), "")

    def get_teammates(self, place) -> list[str]:
        if place.status not in SquadPlace.OPEN:
            return []
        return sorted(
            other.user.display_name
            for other in place.squad.places.all()
            if other.status == SquadPlace.Status.ACCEPTED and other.user_id != place.user_id
        )


class HistoryRowSerializer(serializers.Serializer):
    """One player's representation for the organization: how often and when last."""

    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    club = serializers.CharField(allow_null=True)
    times = serializers.IntegerField()
    last_represented_on = serializers.DateField(allow_null=True)
    squads = serializers.ListField(child=serializers.CharField())
