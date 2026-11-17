from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail

from .models import User
from .tokens import make_reset_params, make_verification_token


def _link(path: str, **params: str) -> str:
    return f"{settings.FRONTEND_URL}{path}?{urlencode(params)}"


def send_verification_email(user: User) -> None:
    link = _link("/verify-email", token=make_verification_token(user))
    send_mail(
        "Verify your Coast TT email",
        f"Hi {user.display_name},\n\n"
        f"Confirm your email to finish creating your Coast TT account:\n{link}\n\n"
        "The link expires in 24 hours. If you didn't sign up, ignore this email.",
        None,
        [user.email],
    )


def send_existing_account_email(user: User) -> None:
    """Sent instead of an error when someone signs up with a registered address (no enumeration)."""
    send_mail(
        "You already have a Coast TT account",
        f"Hi {user.display_name},\n\nSomeone tried to create a Coast TT account with this email, "
        f"but you already have one. Log in at {settings.FRONTEND_URL}/login or reset your password at "
        f"{settings.FRONTEND_URL}/forgot-password.\n\nIf this wasn't you, you can ignore this email.",
        None,
        [user.email],
    )


def send_password_reset_email(user: User) -> None:
    uid, token = make_reset_params(user)
    link = _link("/reset-password", uid=uid, token=token)
    send_mail(
        "Reset your Coast TT password",
        f"Hi {user.display_name},\n\nReset your password here:\n{link}\n\n"
        "The link expires in one hour and works once. If you didn't ask for this, ignore this email.",
        None,
        [user.email],
    )
