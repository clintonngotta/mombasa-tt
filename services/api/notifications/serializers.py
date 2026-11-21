from cryptography.hazmat.primitives.asymmetric import ec
from rest_framework import serializers

from .models import Category, Notification, PushSubscription
from .push import allowed_endpoint
from .webpush import b64url_decode


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


class PushDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushSubscription
        fields = ["id", "label", "created_at", "last_sent_at"]
        read_only_fields = fields


class PushStatusSerializer(serializers.Serializer):
    configured = serializers.BooleanField(help_text="Whether this server sends push messages at all.")
    public_key = serializers.CharField(help_text="The applicationServerKey to subscribe with (base64url).")
    devices = PushDeviceSerializer(many=True)


class PushKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=50)


class PushSubscribeSerializer(serializers.Serializer):
    """A browser's PushSubscription as `subscription.toJSON()` gives it, plus a label for the device."""

    endpoint = serializers.URLField(max_length=1000)
    keys = PushKeysSerializer()
    expirationTime = serializers.IntegerField(required=False, allow_null=True, min_value=0)  # noqa: N815
    label = serializers.CharField(max_length=80, required=False, allow_blank=True, trim_whitespace=True)

    def validate_endpoint(self, value):
        if not allowed_endpoint(value):
            raise serializers.ValidationError("This isn't a browser push service address.")
        return value

    def validate_keys(self, value):
        try:
            if len(b64url_decode(value["auth"])) != 16:
                raise ValueError
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(value["p256dh"]))
        except ValueError as error:
            raise serializers.ValidationError("The browser's push keys aren't valid.") from error
        return value


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)
