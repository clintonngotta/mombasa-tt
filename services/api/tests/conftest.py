import re

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import User

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _clear_throttles():
    cache.clear()


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
