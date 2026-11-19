from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Guest, GuestClaim, GuestClaimEvent, GuestInvitation


class GuestInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestInvitation
        fields = ["id", "email", "status", "created_at", "expires_at"]


class GuestSerializer(serializers.ModelSerializer):
    """A club's guest, for its staff. `id` is the player's id, the one entries and matches use."""

    id = serializers.UUIDField(source="user_id", read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    claimed_by_name = serializers.CharField(source="claimed_by.display_name", read_only=True, default=None)
    invitation = serializers.SerializerMethodField()
    entries = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Guest
        fields = [
            "id",
            "display_name",
            "created_at",
            "claimed_at",
            "claimed_by_name",
            "invitation",
            "entries",
        ]

    @extend_schema_field(GuestInvitationSerializer(allow_null=True))
    def get_invitation(self, guest):
        """The invitation still open, if any."""
        found = next((i for i in guest.invitations.all() if i.is_open), None)
        return GuestInvitationSerializer(found).data if found else None


class GuestWriteSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=80, trim_whitespace=True)


class GuestInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ClaimEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default=None)

    class Meta:
        model = GuestClaimEvent
        fields = ["action", "actor_name", "note", "at"]


class GuestClaimSerializer(serializers.ModelSerializer):
    """A claim for staff, with its audit trail."""

    guest_id = serializers.UUIDField(source="guest.user_id", read_only=True)
    guest_name = serializers.CharField(source="guest.user.display_name", read_only=True)
    claimant_name = serializers.CharField(source="claimant.display_name", read_only=True)
    # The address staff invited, not the account's own: staff learn nothing they didn't already know.
    invited_email = serializers.EmailField(source="invitation.email", read_only=True)
    events = ClaimEventSerializer(many=True, read_only=True)
    clashes = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = GuestClaim
        fields = [
            "id",
            "guest_id",
            "guest_name",
            "claimant_name",
            "invited_email",
            "status",
            "clashes",
            "created_at",
            "resolved_at",
            "events",
        ]


class ClaimNoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, trim_whitespace=True)


class MyGuestInvitationSerializer(serializers.ModelSerializer):
    """An invitation to the signed-in player: who they were entered as, and where."""

    guest_name = serializers.CharField(source="guest.user.display_name", read_only=True)
    organization_name = serializers.CharField(source="guest.organization.name", read_only=True)
    invited_by_name = serializers.CharField(source="invited_by.display_name", read_only=True, default=None)

    class Meta:
        model = GuestInvitation
        fields = ["id", "guest_name", "organization_name", "invited_by_name", "created_at", "expires_at"]


class MyClaimSerializer(serializers.ModelSerializer):
    """What came of accepting: merged, or waiting for the club to sort out a clash."""

    guest_name = serializers.CharField(source="guest.user.display_name", read_only=True)
    organization_name = serializers.CharField(source="guest.organization.name", read_only=True)
    clashes = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = GuestClaim
        fields = ["id", "guest_name", "organization_name", "status", "clashes", "created_at", "resolved_at"]
