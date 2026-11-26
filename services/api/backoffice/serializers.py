from rest_framework import serializers

from accounts.models import User
from core.geography import normalize_place
from core.models import City, Country, Region
from organizations.models import Organization


class OverviewSerializer(serializers.Serializer):
    accounts = serializers.IntegerField()
    accounts_new = serializers.IntegerField(help_text="Joined in the last 30 days.")
    accounts_inactive = serializers.IntegerField()
    platform_admins = serializers.IntegerField()
    organizations = serializers.DictField(child=serializers.IntegerField(), help_text="Count per kind.")
    tournaments = serializers.DictField(child=serializers.IntegerField(), help_text="Count per status.")
    tournaments_awaiting_approval = serializers.IntegerField()
    events_awaiting_review = serializers.IntegerField()


class AccountSerializer(serializers.ModelSerializer):
    """An account as the platform's back office sees it. `email` is null for a phone-only account."""

    email = serializers.SerializerMethodField()
    is_platform_admin = serializers.BooleanField(source="is_superuser", read_only=True)
    organizations = serializers.IntegerField(read_only=True, help_text="Active memberships.")

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone",
            "display_name",
            "email_verified_at",
            "phone_verified_at",
            "is_active",
            "is_platform_admin",
            "organizations",
            "date_joined",
            "last_login",
        ]
        read_only_fields = fields

    def get_email(self, user) -> str | None:
        return user.email if user.can_receive_email else None


class AccountChangeSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(required=False)
    is_platform_admin = serializers.BooleanField(required=False)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({name: "This can't be changed here." for name in unknown})
        if not attrs:
            raise serializers.ValidationError("Nothing to change.")
        return attrs


class PlatformOrganizationSerializer(serializers.ModelSerializer):
    members = serializers.IntegerField(read_only=True)
    admin_name = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "kind", "town", "region", "country", "members", "admin_name", "created_at"]
        read_only_fields = fields


class PlaceNameField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(max_length=100, min_length=2, trim_whitespace=True, **kwargs)

    def to_internal_value(self, data):
        return normalize_place(super().to_internal_value(data))


class PlatformCitySerializer(serializers.ModelSerializer):
    class Meta:
        model = City
        fields = ["id", "name"]
        read_only_fields = fields


class PlatformRegionSerializer(serializers.ModelSerializer):
    cities = PlatformCitySerializer(many=True, read_only=True)

    class Meta:
        model = Region
        fields = ["id", "name", "cities"]
        read_only_fields = fields


class PlatformCountrySerializer(serializers.ModelSerializer):
    regions = PlatformRegionSerializer(many=True, read_only=True)

    class Meta:
        model = Country
        fields = ["code", "name", "catalogue_only", "regions"]
        read_only_fields = fields


class CountryChangeSerializer(serializers.Serializer):
    catalogue_only = serializers.BooleanField()


class PlaceInputSerializer(serializers.Serializer):
    name = PlaceNameField()
