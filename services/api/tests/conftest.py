import re

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _clear_throttles():
    cache.clear()


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    # The production PBKDF2 work factor costs ~1s per hash; tests only need hashing to round-trip.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class BrowserClient(APIClient):
    """Behaves like the PWA: enforces CSRF and echoes the csrftoken cookie on unsafe requests."""

    def __init__(self):
        super().__init__(enforce_csrf_checks=True)
        self.get("/api/v1/auth/csrf/")

    def generic(self, method, path, *args, **kwargs):
        token = self.cookies.get("csrftoken")
        if token and method not in {"GET", "HEAD", "OPTIONS"}:
            kwargs.setdefault("HTTP_X_CSRFTOKEN", token.value)
        return super().generic(method, path, *args, **kwargs)


@pytest.fixture
def client():
    return BrowserClient()


@pytest.fixture
def verified_user(db):
    from django.utils import timezone

    return User.objects.create_user(
        email="ama@example.com", password=PASSWORD, display_name="Ama", email_verified_at=timezone.now()
    )


def link_from(mail, path: str) -> dict[str, str]:
    match = re.search(rf"{re.escape(path)}\?(\S+)", mail.body)
    assert match, f"no {path} link in email"
    from urllib.parse import parse_qsl

    return dict(parse_qsl(match.group(1)))


@pytest.fixture(autouse=True)
def _attachments_in_tmp(settings, tmp_path):
    # Uploaded files go to a throwaway folder, never into the checkout.
    settings.STORAGES = {
        **settings.STORAGES,
        "attachments": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": tmp_path / "attachments"},
        },
    }


# A club with its admin signed in: the setting most organization and tournament tests start from.
@pytest.fixture
def admin(db):
    from .helpers import make_user

    return make_user("admin@example.com", display_name="Club Admin")


@pytest.fixture
def club(admin):
    from .test_roles import create_club

    return create_club(admin)


@pytest.fixture
def staff(admin):
    from .helpers import logged_in

    return logged_in(admin)
