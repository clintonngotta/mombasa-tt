from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import EmailField, PhoneField
from core.geography import CountryField, validate_location

from .models import Guest, GuestClaim, GuestClaimEvent, GuestInvitation


class GuestInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestInvitation
        fields = ["id", "email", "phone", "status", "created_at", "expires_at"]


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
    """Where to reach the player: an email (we send the link), a phone (staff share the link), or both."""

    email = EmailField(required=False, allow_blank=True)
    phone = PhoneField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError({"email": "Give an email address or a phone number."})
        return attrs


class GuestCreateSerializer(GuestWriteSerializer):
    """A new guest; with an email or phone, they are invited at once."""

    email = EmailField(required=False, allow_blank=True)
    phone = PhoneField(required=False, allow_blank=True, allow_null=True)


class InvitedGuestSerializer(GuestSerializer):
    """A guest just invited, with the link to share. The link is shown this once: only its hash is kept."""

    invite_link = serializers.CharField(read_only=True)

    class Meta(GuestSerializer.Meta):
        fields = [*GuestSerializer.Meta.fields, "invite_link"]


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


class InvitationEntrySerializer(serializers.Serializer):
    tournament_id = serializers.UUIDField()
    tournament_name = serializers.CharField()
    event_name = serializers.CharField()
    starts_on = serializers.DateField()


class InvitationDetailSerializer(serializers.Serializer):
    """What an invitation link shows the person who opens it: who they were entered as, where, by whom,
    and the tournaments they are in. The contact details are the ones staff typed for them."""

    guest_name = serializers.CharField()
    organization_name = serializers.CharField()
    invited_by_name = serializers.CharField(allow_null=True)
    email = serializers.CharField()
    phone = serializers.CharField()
    expires_at = serializers.DateTimeField()
    entries = InvitationEntrySerializer(many=True)


class InvitationJoinSerializer(serializers.Serializer):
    """The invitee's own details for their new account: email, phone or both to sign in with."""

    display_name = serializers.CharField(max_length=80, trim_whitespace=True)
    email = EmailField(required=False, allow_blank=True)
    phone = PhoneField(required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    country = CountryField(max_length=2, required=False)
    region = serializers.CharField(max_length=100, required=False)
    city = serializers.CharField(max_length=100, required=False)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError(
                {"email": "Give an email address or a phone number to log in with."}
            )
        validate_location(attrs)
        candidate = User(email=attrs.get("email") or "", display_name=attrs["display_name"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class InvitationJoinedSerializer(serializers.Serializer):
    """`signed_in`: the account is ready and this browser is signed in. Otherwise the email the player
    chose needs verifying first (a link is on its way)."""

    signed_in = serializers.BooleanField()
