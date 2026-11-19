from rest_framework import serializers

from .models import Category, Notification


class NotificationSerializer(serializers.ModelSerializer):
    read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "category", "title", "body", "link", "created_at", "read", "superseded"]
        read_only_fields = fields

    def get_read(self, alert) -> bool:
        return alert.read_at is not None


class PreferenceSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=Category.choices)
    label = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField()
    locked = serializers.BooleanField(read_only=True, help_text="Can't be switched off.")


class PreferencesSerializer(serializers.Serializer):
    preferences = PreferenceSerializer(many=True)


class UnreadSerializer(serializers.Serializer):
    unread = serializers.IntegerField()


class AnnouncementSerializer(serializers.Serializer):
    """A message from the organization to an explicit audience."""

    title = serializers.CharField(max_length=140, trim_whitespace=True)
    body = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)
    audience = serializers.ChoiceField(choices=["members", "event", "people"])
    event_id = serializers.UUIDField(required=False)
    user_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=500)

    def validate(self, attrs):
        if attrs["audience"] == "event" and not attrs.get("event_id"):
            raise serializers.ValidationError({"event_id": "Choose the event."})
        if attrs["audience"] == "people" and not attrs.get("user_ids"):
            raise serializers.ValidationError({"user_ids": "Choose who gets it."})
        return attrs


class SentSerializer(serializers.Serializer):
    sent = serializers.IntegerField()
