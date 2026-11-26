from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.geography import CountryField, validate_location

from .models import User, normalize_email
from .phones import looks_like_phone, normalize_phone


class UserSerializer(serializers.ModelSerializer):
    """The signed-in player's own account. `email` is null for an account that signs in by phone only."""

    email = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone",
            "display_name",
            "email_verified_at",
            "phone_verified_at",
            "date_joined",
        ]
        read_only_fields = fields

    def get_email(self, user) -> str | None:
        return user.email if user.can_receive_email else None


class EmailField(serializers.EmailField):
    def to_internal_value(self, data):
        return normalize_email(super().to_internal_value(data))


class ReturnPathField(serializers.CharField):
    """Where the app takes a new player once they've verified and onboarded, such as the event they
    signed up to enter (TASK-035). A path within the app only: never another site."""

    def __init__(self, **kwargs):
        super().__init__(max_length=300, required=False, allow_blank=True, **kwargs)

    def to_internal_value(self, data):
        path = super().to_internal_value(data)
        outside = not path.startswith("/") or path.startswith("//") or "\\" in path
        if path and (outside or not path.isprintable() or " " in path):
            raise serializers.ValidationError("Use a path within the app.")
        return path


class SignUpSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=80, trim_whitespace=True)
    email = EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    country = CountryField(max_length=2, required=False)
    region = serializers.CharField(max_length=100, required=False)
    city = serializers.CharField(max_length=100, required=False)
    next = ReturnPathField()

    def validate(self, attrs):
        validate_location(attrs)
        candidate = User(email=attrs["email"], display_name=attrs["display_name"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class PhoneField(serializers.CharField):
    """A phone number as typed, returned in E.164. Numbers without a country code are Kenyan."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 32)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        text = super().to_internal_value(data)
        if not text:
            return None
        phone = normalize_phone(text)
        if phone is None:
            raise serializers.ValidationError(
                "Enter a phone number such as 0712 345 678 or +254 712 345 678."
            )
        return phone


class LogInSerializer(serializers.Serializer):
    """Sign in with an email address or a phone number. `email` is the older name for `login`."""

    login = serializers.CharField(max_length=254, required=False, trim_whitespace=True)
    email = serializers.CharField(max_length=254, required=False, write_only=True, trim_whitespace=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        given = attrs.get("login") or attrs.get("email")
        if not given:
            raise serializers.ValidationError({"login": "Enter your email address or phone number."})
        if looks_like_phone(given):
            return {"phone": normalize_phone(given), "password": attrs["password"]}
        return {"email": normalize_email(given), "password": attrs["password"]}


class AccountUpdateSerializer(serializers.Serializer):
    """What players change about their own account. A new phone number starts unconfirmed."""

    display_name = serializers.CharField(max_length=80, trim_whitespace=True, required=False)
    phone = PhoneField(required=False, allow_blank=True, allow_null=True)


class EmailOnlySerializer(serializers.Serializer):
    email = EmailField()


class ResendVerificationSerializer(EmailOnlySerializer):
    next = ReturnPathField()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
