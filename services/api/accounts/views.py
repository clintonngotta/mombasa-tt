from django.contrib.auth import authenticate, login, logout, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException

from . import emails
from .models import User
from .serializers import (
    EmailOnlySerializer,
    LogInSerializer,
    PasswordResetConfirmSerializer,
    SignUpSerializer,
    TokenSerializer,
    UserSerializer,
)
from .tokens import read_reset_params, read_verification_token

ACCEPTED = {"message": "If that address can receive mail from us, an email is on its way."}


@method_decorator(csrf_protect, name="dispatch")
class PublicAuthView(APIView):
    """Anonymous endpoints. DRF skips CSRF for anonymous users, so enforce it explicitly
    (prevents login CSRF)."""

    authentication_classes = []
    permission_classes = [AllowAny]


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={204: None})
    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class SignUpView(PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(request=SignUpSerializer, responses={201: None})
    def post(self, request):
        serializer = SignUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        existing = User.objects.filter(email=data["email"]).first()
        if existing:
            # Same response as a new signup; the owner hears about it by email instead (REQ-003).
            emails.send_existing_account_email(existing)
        else:
            user = User.objects.create_user(
                email=data["email"], password=data["password"], display_name=data["display_name"]
            )
            emails.send_verification_email(user)
        return Response(ACCEPTED, status=status.HTTP_201_CREATED)


class ResendVerificationView(PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(request=EmailOnlySerializer, responses={202: None})
    def post(self, request):
        serializer = EmailOnlySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email=serializer.validated_data["email"], is_active=True, email_verified_at__isnull=True
        ).first()
        if user:
            emails.send_verification_email(user)
        return Response(ACCEPTED, status=status.HTTP_202_ACCEPTED)


class VerifyEmailView(PublicAuthView):
    @extend_schema(request=TokenSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = read_verification_token(serializer.validated_data["token"])
        if user is None:
            raise ApiException("invalid_token", "This verification link is invalid or has expired.")
        if not user.is_email_verified:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(UserSerializer(user).data)


class LogInView(PublicAuthView):
    throttle_scope = "auth_login"

    @extend_schema(request=LogInSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = LogInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, **serializer.validated_data)
        if user is None:
            # Unknown email and wrong password are indistinguishable (Django still hashes for unknown users).
            raise ApiException("invalid_credentials", "That email and password don't match an account.")
        if not user.is_email_verified:
            # Only revealed after the correct password, so it doesn't enumerate accounts.
            raise ApiException(
                "email_unverified", "Verify your email before logging in.", status.HTTP_403_FORBIDDEN
            )
        login(request, user)
        return Response(UserSerializer(user).data)


class LogOutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        logout(request)  # flushes the session server-side
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetView(PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(request=EmailOnlySerializer, responses={202: None})
    def post(self, request):
        serializer = EmailOnlySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email=serializer.validated_data["email"], is_active=True).first()
        if user and user.has_usable_password():
            emails.send_password_reset_email(user)
        return Response(ACCEPTED, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(request=PasswordResetConfirmSerializer, responses={204: None})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = read_reset_params(data["uid"], data["token"])
        if user is None:
            raise ApiException("invalid_token", "This reset link is invalid or has expired.")

        try:
            password_validation.validate_password(data["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc

        # A new password changes the session auth hash, which ends every existing session (REQ-003).
        user.set_password(data["password"])
        if not user.is_email_verified:
            user.email_verified_at = timezone.now()  # they proved inbox ownership
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)
