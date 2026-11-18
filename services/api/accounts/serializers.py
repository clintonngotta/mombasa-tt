from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from core.geography import CountryField, validate_location

from .models import User, normalize_email


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "display_name", "email_verified_at", "date_joined"]
        read_only_fields = fields


class EmailField(serializers.EmailField):
    def to_internal_value(self, data):
        return normalize_email(super().to_internal_value(data))


class SignUpSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=80, trim_whitespace=True)
    email = EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    country = CountryField(max_length=2, required=False)
    region = serializers.CharField(max_length=100, required=False)
    city = serializers.CharField(max_length=100, required=False)

    def validate(self, attrs):
        validate_location(attrs)
        candidate = User(email=attrs["email"], display_name=attrs["display_name"])
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class LogInSerializer(serializers.Serializer):
    email = EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class EmailOnlySerializer(serializers.Serializer):
    email = EmailField()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
