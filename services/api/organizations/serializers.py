from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .access import membership_permissions
from .models import Invitation, JoinRequest, Membership, Organization, Role
from .permissions import Permission


class OrganizationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "kind"]


class RoleSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "key", "name"]
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    """A role and its permissions (REQ-005). Admin always reports every permission."""

    name = serializers.CharField(max_length=60, trim_whitespace=True)
    permissions = serializers.ListField(
        child=serializers.ChoiceField(choices=Permission.choices), required=False
    )
    member_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Role
        fields = ["id", "key", "name", "permissions", "member_count"]
        read_only_fields = ["id", "key", "member_count"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["permissions"] = sorted(instance.permission_set)
        return data

    def validate_permissions(self, value):
        return sorted(set(value))


class PermissionInfoSerializer(serializers.Serializer):
    code = serializers.ChoiceField(choices=Permission.choices)
    label = serializers.CharField()


class MembershipSerializer(serializers.ModelSerializer):
    """The player's own membership: roles held and the permissions they add up to, so the app can show
    only the actions the server will allow."""

    organization = OrganizationSerializer(read_only=True)
    roles = RoleSummarySerializer(many=True, read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "organization", "roles", "permissions", "status", "joined_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.ChoiceField(choices=Permission.choices)))
    def get_permissions(self, membership) -> list[str]:
        return sorted(membership_permissions(membership))


class MemberSerializer(serializers.ModelSerializer):
    """Staff view of a member: display name and roles, never email or contact details."""

    display_name = serializers.CharField(source="user.display_name", read_only=True)
    roles = RoleSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "display_name", "roles", "joined_at"]
        read_only_fields = fields


class MemberRolesSerializer(serializers.Serializer):
    roles = serializers.ListField(child=serializers.UUIDField(), max_length=20)


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
