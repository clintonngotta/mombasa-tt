from rest_framework import serializers

from .models import PlayerProfile


class ProfileSerializer(serializers.ModelSerializer):
    """The owner's own view of their profile. `display_name` is written through to User."""

    # allow_blank lets validate_display_name give the friendly message instead of the default one.
    display_name = serializers.CharField(
        source="user.display_name", max_length=80, trim_whitespace=True, allow_blank=True
    )
    onboarding_completed = serializers.SerializerMethodField()

    class Meta:
        model = PlayerProfile
        fields = [
            "display_name",
            "nickname",
            "hand",
            "grip",
            "style",
            "experience",
            "bio",
            "directory_opt_in",
            "goals",
            "onboarding_completed",
        ]
        read_only_fields = ["goals", "onboarding_completed"]

    def get_onboarding_completed(self, obj) -> bool:
        return obj.onboarding_completed_at is not None

    def validate_display_name(self, value):
        if not value:
            raise serializers.ValidationError("Enter the name other players will see.")
        return value

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


class DirectoryPlayerSerializer(serializers.Serializer):
    """Public directory card: name and organizations only. No email, bio, location or other details."""

    id = serializers.UUIDField(source="user.id")
    display_name = serializers.CharField(source="user.display_name")
    nickname = serializers.CharField()
    clubs = serializers.SerializerMethodField()

    def get_clubs(self, obj) -> list[str]:
        return [m.organization.name for m in obj.user.memberships.all()]
