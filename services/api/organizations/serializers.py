from rest_framework import serializers

from .models import Invitation, JoinRequest, Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "kind"]


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "organization", "role", "status", "joined_at"]
        read_only_fields = fields


class JoinRequestSerializer(serializers.ModelSerializer):
    """Staff view of a request. Shows the requester's display name only, never their email."""

    display_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = JoinRequest
        fields = ["id", "user", "display_name", "status", "created_at", "decided_at"]
        read_only_fields = fields


class MyJoinRequestSerializer(serializers.ModelSerializer):
    """The requester's view: which organization (name and town, so the app can list them) and the outcome."""

    organization = OrganizationSerializer(read_only=True)

    class Meta:
        model = JoinRequest
        fields = ["id", "organization", "status", "created_at", "decided_at"]
        read_only_fields = fields


class InvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class InvitationSerializer(serializers.ModelSerializer):
    """Staff view of an invitation they sent."""

    class Meta:
        model = Invitation
        fields = ["id", "email", "status", "created_at", "expires_at", "decided_at"]
        read_only_fields = fields


class MyInvitationSerializer(serializers.ModelSerializer):
    """The invitee's view: which organization, and who invited them (display name only)."""

    organization = OrganizationSerializer(read_only=True)
    invited_by_name = serializers.CharField(source="invited_by.display_name", read_only=True, default="")

    class Meta:
        model = Invitation
        fields = ["id", "organization", "invited_by_name", "status", "created_at", "expires_at"]
        read_only_fields = fields
