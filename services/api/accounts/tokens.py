from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User

_VERIFY_SALT = "accounts.verify-email"


def make_verification_token(user: User) -> str:
    # Bound to the address so a later email change invalidates outstanding links.
    return signing.dumps({"u": str(user.id), "e": user.email}, salt=_VERIFY_SALT)


def read_verification_token(token: str) -> User | None:
    try:
        data = signing.loads(token, salt=_VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
        return User.objects.get(id=data["u"], email=data["e"], is_active=True)
    except (signing.BadSignature, KeyError, ValueError, User.DoesNotExist):
        return None


def make_reset_params(user: User) -> tuple[str, str]:
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


def read_reset_params(uid: str, token: str) -> User | None:
    """Django's reset token embeds the password hash and last login, so it is single-use."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        return None
    return user if default_token_generator.check_token(user, token) else None
