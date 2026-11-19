from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.geography import CountryField, validate_location
from core.timezones import validate_timezone

from .access import membership_permissions
from .member_fields import MAX_OPTIONS
from .models import Invitation, JoinRequest, MemberField, Membership, Organization, Role
from .permissions import Permission


class OrganizationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])
    country = CountryField(max_length=2, required=False, allow_blank=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "country", "region", "kind", "timezone"]

    def validate_kind(self, value):
        """A regional body is set up by its region's official (POST /regional-bodies/), never by picking
        the kind, and no organization changes into or out of one."""
        body = Organization.Kind.REGIONAL_BODY
        if value == body and not (self.instance and self.instance.is_body):
            raise serializers.ValidationError("Choose club, facility or both.")
        if self.instance and self.instance.is_body and value != body:
            raise serializers.ValidationError("A regional body stays a regional body.")
        return value

    def validate(self, attrs):
        validate_location(attrs, self.instance, city_field="town", legacy_town=True)
        if self.instance and self.instance.is_body:
            for name in ("country", "region"):
                if name in attrs and attrs[name] != getattr(self.instance, name):
                    raise serializers.ValidationError({name: "A regional body's region doesn't change."})
        return attrs


class OrganizationLocationSerializer(serializers.ModelSerializer):
    country = CountryField(max_length=2)

    class Meta:
        model = Organization
        fields = ["country", "region", "town"]
        extra_kwargs = {"region": {"allow_blank": False, "required": True}}

    def validate(self, attrs):
        validate_location(attrs, self.instance, city_field="town")
        return attrs


class ManagementOrganizationSerializer(serializers.Serializer):
    organization = OrganizationSerializer()
    authority = serializers.ChoiceField(choices=["platform", "country", "regional"])
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=Permission.choices))


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


class MemberFieldSerializer(serializers.ModelSerializer):
    """A custom member field definition (REQ-005). Its type is fixed once created, so existing values
    never change meaning; `options` apply to selection fields only."""

    label = serializers.CharField(max_length=80, trim_whitespace=True)
    options = serializers.ListField(
        child=serializers.CharField(max_length=60, trim_whitespace=True),
        required=False,
        max_length=MAX_OPTIONS,
    )

    class Meta:
        model = MemberField
        fields = ["id", "label", "kind", "options", "required", "visibility", "retired_at"]
        read_only_fields = ["id", "retired_at"]

    def validate_kind(self, value):
        if self.instance and value != self.instance.kind:
            raise serializers.ValidationError("A field's type can't change. Retire it and add a new one.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind") or self.instance.kind
        if "options" in attrs or not self.instance:
            # Options differing only by case would be indistinguishable to members; the first one wins.
            seen: set[str] = set()
            options = []
            for option in attrs.get("options", []):
                if option.lower() not in seen:
                    seen.add(option.lower())
                    options.append(option)
            if kind == MemberField.Kind.CHOICE and len(options) < 2:
                raise serializers.ValidationError({"options": "Add at least two options."})
            if kind != MemberField.Kind.CHOICE and options:
                raise serializers.ValidationError({"options": "Only selection fields have options."})
            attrs["options"] = options
        return attrs


@extend_schema_field(
    {"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}], "nullable": True}
)
class FieldValueField(serializers.JSONField):
    """Text, selection and ISO date values are strings; number and yes/no values keep their JSON type.
    Null means no answer."""


class MemberFieldEntrySerializer(serializers.Serializer):
    """One field with the member's value for it."""

    field = MemberFieldSerializer(read_only=True)
    value = FieldValueField(read_only=True, allow_null=True)


class MemberFieldValuesSerializer(serializers.Serializer):
    """Values to change, keyed by field id. Fields left out keep their value; null clears one."""

    values = serializers.DictField(child=FieldValueField(allow_null=True))
