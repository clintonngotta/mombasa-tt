from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from accounts.serializers import EmailField, PhoneField
from core.geography import (
    CountryField,
    coordinate_field,
    directions_field,
    validate_coordinates,
    validate_location,
)
from core.timezones import validate_timezone

from .access import membership_permissions
from .member_fields import MAX_OPTIONS
from .models import BODY_KINDS, Invitation, JoinRequest, MemberField, Membership, Organization, Role
from .permissions import Permission


def description_field():
    return serializers.CharField(max_length=2000, allow_blank=True, required=False, trim_whitespace=True)


def validate_no_place_for_team(attrs, instance=None):
    """A team has a home town but no training place (REQ-057): no directions and no map position, so it
    is never offered as somewhere to go."""
    kind = attrs.get("kind", instance.kind if instance else Organization.Kind.CLUB)
    if kind != Organization.Kind.TEAM:
        return
    for name in ("directions", "latitude", "longitude"):
        if attrs.get(name) not in (None, ""):
            raise serializers.ValidationError(
                {name: "A team has no training place. Register a club for a place people train at."}
            )


class OrganizationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    timezone = serializers.CharField(max_length=64, required=False, validators=[validate_timezone])
    country = CountryField(max_length=2, required=False, allow_blank=True)
    directions = directions_field()
    latitude = coordinate_field(90)
    longitude = coordinate_field(180)
    description = description_field()

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "country", "region", "directions", "latitude", "longitude"]
        fields += ["description", "kind", "timezone"]

    def validate_kind(self, value):
        """A regional or national body is created by a platform super admin (POST /regional-bodies/),
        never by picking the kind, and no organization changes into or out of one."""
        current = self.instance.kind if self.instance else None
        if value in BODY_KINDS and value != current:
            raise serializers.ValidationError("Choose club, team, facility or club and facility.")
        if self.instance and self.instance.is_body and value != current:
            raise serializers.ValidationError("A governing body stays what it is.")
        # A coach's organizing desk is made from their coach profile (POST /me/coach-profile/organizer/).
        coaching = Organization.Kind.COACHING
        if value == coaching and not (self.instance and self.instance.is_coaching):
            raise serializers.ValidationError("Choose club, team, facility or club and facility.")
        if self.instance and self.instance.is_coaching and value != coaching:
            raise serializers.ValidationError("A coach's organizing desk stays one.")
        return value

    def validate(self, attrs):
        validate_location(attrs, self.instance, city_field="town", legacy_town=True)
        validate_coordinates(attrs, self.instance)
        validate_no_place_for_team(attrs, self.instance)
        if self.instance and self.instance.is_body:
            for name in ("country", "region"):
                if name in attrs and attrs[name] != getattr(self.instance, name):
                    raise serializers.ValidationError({name: "A governing body's region doesn't change."})
        return attrs


class NearbyOrganizationSerializer(OrganizationSerializer):
    """A club found near a point, with how far away it is."""

    distance_m = serializers.SerializerMethodField()

    class Meta(OrganizationSerializer.Meta):
        fields = [*OrganizationSerializer.Meta.fields, "distance_m"]
        read_only_fields = fields

    def get_distance_m(self, organization) -> int:
        return round(organization.distance_m)


class NearbyOrganizationsSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = NearbyOrganizationSerializer(many=True)


class OrganizationLocationSerializer(serializers.ModelSerializer):
    """The club's settings that roles.manage edits: where it is and what it is about."""

    country = CountryField(max_length=2)
    description = description_field()
    directions = directions_field()
    latitude = coordinate_field(90)
    longitude = coordinate_field(180)

    class Meta:
        model = Organization
        fields = ["country", "region", "town", "directions", "latitude", "longitude", "description"]
        extra_kwargs = {"region": {"allow_blank": False, "required": True}}

    def validate(self, attrs):
        validate_location(attrs, self.instance, city_field="town")
        validate_coordinates(attrs, self.instance)
        validate_no_place_for_team(attrs, self.instance)
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
    # Held only in regional and national bodies; the role editor hides it elsewhere.
    body_only = serializers.BooleanField()


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
    """Staff view of a member: display name and roles, never email or contact details. `is_guest` marks a
    member staff added who hasn't joined from their link yet."""

    display_name = serializers.CharField(source="user.display_name", read_only=True)
    roles = RoleSummarySerializer(many=True, read_only=True)
    is_guest = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "user", "display_name", "roles", "joined_at", "is_guest"]
        read_only_fields = fields

    def get_is_guest(self, membership) -> bool:
        guest = getattr(membership.user, "guest", None)
        return guest is not None and guest.claimed_by_id is None


class MemberAddSerializer(serializers.Serializer):
    """Someone staff add to the club directly: a name, and an email (we send the link), a phone (staff
    share the link) or both."""

    display_name = serializers.CharField(max_length=80, trim_whitespace=True)
    email = EmailField(required=False, allow_blank=True)
    phone = PhoneField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError({"email": "Give an email address or a phone number."})
        return attrs


class AddedMemberSerializer(MemberSerializer):
    """A member just added, with the link to share. Shown this once: only its hash is kept."""

    invite_link = serializers.CharField(read_only=True)

    class Meta(MemberSerializer.Meta):
        fields = [*MemberSerializer.Meta.fields, "invite_link"]


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
    """Invite by email, or a player found in the player directory: one of the two."""

    email = serializers.EmailField(required=False)
    player_id = serializers.UUIDField(required=False)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def validate(self, attrs):
        if ("email" in attrs) == ("player_id" in attrs):
            raise serializers.ValidationError({"email": "Give an email address or choose a player."})
        return attrs


class InvitationSerializer(serializers.ModelSerializer):
    """Staff view of an invitation they sent. An invited player is shown by name; their email isn't."""

    invitee_name = serializers.CharField(source="invitee.display_name", read_only=True, default=None)

    class Meta:
        model = Invitation
        fields = ["id", "email", "invitee_name", "status", "created_at", "expires_at", "decided_at"]
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
