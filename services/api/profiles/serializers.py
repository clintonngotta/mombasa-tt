from rest_framework import serializers

from attachments.serializers import AttachmentLinkSerializer
from core.geography import CountryField, validate_location

from .models import PlayerProfile


class ProfileSerializer(serializers.ModelSerializer):
    """The owner's own view of their profile. `display_name` is written through to User."""

    # allow_blank lets validate_display_name give the friendly message instead of the default one.
    display_name = serializers.CharField(
        source="user.display_name", max_length=80, trim_whitespace=True, allow_blank=True
    )
    onboarding_completed = serializers.SerializerMethodField()
    # Changed through /me/avatar/ (a file upload), not through this serializer.
    avatar = AttachmentLinkSerializer(source="avatar_id", read_only=True, allow_null=True)
    country = CountryField(max_length=2, required=False, allow_blank=True)

    class Meta:
        model = PlayerProfile
        fields = [
            "display_name",
            "avatar",
            "nickname",
            "hand",
            "grip",
            "style",
            "experience",
            "bio",
            "country",
            "region",
            "city",
            "directory_opt_in",
            "published_details",
            "goals",
            "onboarding_completed",
        ]
        read_only_fields = ["avatar", "goals", "onboarding_completed"]

    def get_onboarding_completed(self, obj) -> bool:
        return obj.onboarding_completed_at is not None

    def validate_display_name(self, value):
        if not value:
            raise serializers.ValidationError("Enter the name other players will see.")
        return value

    def validate_published_details(self, value):
        return list(dict.fromkeys(value))

    def validate(self, attrs):
        validate_location(attrs, self.instance)
        return attrs

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        if "display_name" in user_data:
            instance.user.display_name = user_data["display_name"]
            instance.user.save(update_fields=["display_name"])
        return super().update(instance, validated_data)


class GoalsSerializer(serializers.Serializer):
    goals = serializers.ListField(
        child=serializers.ChoiceField(choices=PlayerProfile.Goal.choices), allow_empty=True, max_length=6
    )

    def validate_goals(self, value):
        return list(dict.fromkeys(value))  # drop duplicates, keep order


class AvatarUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="JPEG, PNG or WebP, up to 5 MB")


class DirectoryPlayerSerializer(serializers.Serializer):
    """Directory card of a listed player: name, picture and organizations only. No email, bio, location
    or other details."""

    id = serializers.UUIDField(source="user.id")
    display_name = serializers.CharField(source="user.display_name")
    nickname = serializers.CharField()
    avatar = AttachmentLinkSerializer(source="avatar_id", read_only=True, allow_null=True)
    clubs = serializers.SerializerMethodField()

    def get_clubs(self, obj) -> list[str]:
        return [m.organization.name for m in obj.user.memberships.all()]


class PublishedOnly:
    """Reads the attribute only if the player published it and it isn't blank; otherwise null."""

    def get_attribute(self, instance):
        value = super().get_attribute(instance)
        return value if value and self.field_name in instance.published_details else None


class PublishedChoiceField(PublishedOnly, serializers.ChoiceField):
    pass


class PublishedCharField(PublishedOnly, serializers.CharField):
    pass


class PlayerSerializer(DirectoryPlayerSerializer):
    """Public player page: the directory card plus only the extended details the player published.
    Unpublished or blank details are null. Never email, location or contact details."""

    hand = PublishedChoiceField(choices=PlayerProfile.Hand.choices, read_only=True, allow_null=True)
    grip = PublishedChoiceField(choices=PlayerProfile.Grip.choices, read_only=True, allow_null=True)
    style = PublishedCharField(read_only=True, allow_null=True)
    experience = PublishedChoiceField(
        choices=PlayerProfile.Experience.choices, read_only=True, allow_null=True
    )
    bio = PublishedCharField(read_only=True, allow_null=True)


class SignedOutPlayerSerializer(PlayerSerializer):
    """A player's page to a signed-out visitor (TASK-035): the same shape, but the name alone. The
    photo, nickname, clubs and published details are for signed-in players, as the directory is."""

    def to_representation(self, instance):
        shown = {"id": str(instance.user.id), "display_name": instance.user.display_name}
        shown |= {"nickname": "", "avatar": None, "clubs": []}
        return shown | {field: None for field in ("hand", "grip", "style", "experience", "bio")}
