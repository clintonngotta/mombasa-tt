from django.contrib.auth import authenticate, login, logout, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from profiles.models import PlayerProfile

from . import emails
from .models import User
from .serializers import (
    AccountUpdateSerializer,
    EmailOnlySerializer,
    LogInSerializer,
    PasswordResetConfirmSerializer,
    ResendVerificationSerializer,
    SignUpSerializer,
    TokenSerializer,
    UserSerializer,
)
from .tokens import read_add_email_token, read_reset_params, read_verification_token

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
            emails.send_existing_account_email(existing, data.get("next", ""))
        else:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=data["email"], password=data["password"], display_name=data["display_name"]
                )
                if data.get("country"):
                    PlayerProfile.objects.create(
                        user=user, country=data["country"], region=data["region"], city=data["city"]
                    )
            emails.send_verification_email(user, data.get("next", ""))
        return Response(ACCEPTED, status=status.HTTP_201_CREATED)


class ResendVerificationView(PublicAuthView):
    throttle_scope = "auth_email"

    @extend_schema(request=ResendVerificationSerializer, responses={202: None})
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email=serializer.validated_data["email"], is_active=True, email_verified_at__isnull=True
        ).first()
        if user:
            emails.send_verification_email(user, serializer.validated_data.get("next", ""))
        return Response(ACCEPTED, status=status.HTTP_202_ACCEPTED)


class VerifyEmailView(PublicAuthView):
    @extend_schema(request=TokenSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        user = read_verification_token(token)
        if user is None:
            user = self.added_email(token)
        if user is None:
            raise ApiException("invalid_token", "This verification link is invalid or has expired.")
        if not user.is_email_verified:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(UserSerializer(user).data)

    def added_email(self, token: str):
        """A link sent by AddEmailView: put the confirmed address on the account, if it is still free and
        the account still has none of its own."""
        found = read_add_email_token(token)
        if found is None:
            return None
        user, email = found
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            if user.can_receive_email and user.is_email_verified:
                return user if user.email == email else None
            if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                return None
            user.email, user.email_verified_at = email, timezone.now()
            user.save(update_fields=["email", "email_verified_at"])
        return user


class AddEmailView(APIView):
    """POST /auth/me/email/: an account without a confirmed email address of its own (one that signs in
    by phone) asks to add one. A link goes to the address; nothing changes until it is opened. The answer
    is the same whether or not the address can be used."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "auth_email"

    @extend_schema(request=EmailOnlySerializer, responses={202: None})
    def post(self, request):
        serializer = EmailOnlySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, email = request.user, serializer.validated_data["email"]
        if user.can_receive_email and user.is_email_verified:
            raise ApiException("email_set", "Your account already has a confirmed email address.", 409)
        holder = User.objects.filter(email=email).exclude(pk=user.pk).first()
        if holder is None:
            emails.send_add_email_email(user, email)
        elif holder.can_receive_email:
            emails.send_existing_account_email(holder)  # its owner hears; the caller learns nothing
        return Response(ACCEPTED, status=status.HTTP_202_ACCEPTED)


class LogInView(PublicAuthView):
    throttle_scope = "auth_login"

    @extend_schema(request=LogInSerializer, responses={200: UserSerializer})
    def post(self, request):
        serializer = LogInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        given = serializer.validated_data
        email = given.get("email")
        if "phone" in given:
            # A phone number signs in as the account holding it. An unknown or malformed number still
            # goes through authenticate() with an address nobody has, so it costs the same password hash.
            holder = User.objects.filter(phone=given["phone"]).first() if given["phone"] else None
            email = holder.email if holder else "no-account@invalid"
        user = authenticate(request, email=email, password=given["password"])
        if user is None:
            # Unknown email or phone and wrong password are indistinguishable (Django still hashes).
            raise ApiException(
                "invalid_credentials", "That email or phone number and password don't match an account."
            )
        if not user.is_verified:
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

    def get_throttles(self):
        # Changing the phone tells whether a number is taken, so changes are rate limited.
        self.throttle_scope = "auth_email" if self.request.method == "PATCH" else None
        return super().get_throttles()

    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=AccountUpdateSerializer, responses={200: UserSerializer})
    def patch(self, request):
        serializer = AccountUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user
        changed = []
        if "display_name" in data:
            user.display_name = data["display_name"]
            changed.append("display_name")
        if "phone" in data and data["phone"] != user.phone:
            if not user.is_email_verified:
                # The phone may be how this account signs in: keep it until a verified email can.
                raise ApiException(
                    "phone_locked", "Your phone number can change once your email address is verified.", 409
                )
            if data["phone"] and User.objects.filter(phone=data["phone"]).exclude(pk=user.pk).exists():
                raise ApiException("phone_taken", "That phone number is on another account.", 409)
            user.phone = data["phone"]
            user.phone_verified_at = None
            changed += ["phone", "phone_verified_at"]
        if changed:
            user.save(update_fields=changed)
        return Response(UserSerializer(user).data)
