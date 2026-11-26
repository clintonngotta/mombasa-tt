"""Allowed origins, admin login limits, push redirects and production settings guards."""

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.core.cache import cache

from config.asgi import application
from notifications import webpush

from .conftest import BrowserClient
from .helpers import PASSWORD, make_user

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"


def log_in(client, **headers):
    return client.post(LOGIN, {"email": "ama@example.com", "password": PASSWORD}, format="json", **headers)


def test_a_page_on_another_site_cannot_post_to_the_api(settings):
    make_user("ama@example.com")
    settings.CSRF_TRUSTED_ORIGINS = ["https://app.example.com"]
    visitor = BrowserClient()

    refused = log_in(visitor, HTTP_ORIGIN="https://evil.example")
    assert refused.status_code == 403 and refused.json()["code"] == "origin_not_allowed"
    assert log_in(visitor, HTTP_ORIGIN="null").status_code == 403
    # Lookalikes of an allowed origin are not it.
    assert log_in(visitor, HTTP_ORIGIN="https://app.example.com.evil.example").status_code == 403
    assert log_in(visitor, HTTP_ORIGIN="http://app.example.com").status_code == 403

    # The API's own origin, a configured one, and clients that send no Origin carry on to the usual checks.
    assert log_in(visitor, HTTP_ORIGIN="http://testserver").status_code == 200
    assert log_in(BrowserClient(), HTTP_ORIGIN="https://app.example.com").status_code == 200
    assert log_in(BrowserClient()).status_code == 200
    # Reads are left alone: without CORS headers the other site can't read the answer anyway.
    assert visitor.get("/api/v1/auth/csrf/", HTTP_ORIGIN="https://evil.example").status_code != 403


def test_a_websocket_from_another_site_is_refused():
    async def attempt():
        socket = WebsocketCommunicator(
            application,
            "/api/v1/ws/tournaments/00000000-0000-0000-0000-000000000000/",
            headers=[(b"origin", b"https://evil.example")],
        )
        connected, _ = await socket.connect()
        await socket.disconnect()
        return connected

    assert async_to_sync(attempt)() is False


def test_admin_login_guessing_is_rate_limited(client):
    cache.clear()
    answers = [
        client.post("/django-admin/login/", {"username": "root@example.com", "password": "guess"}).status_code
        for _ in range(11)
    ]
    assert 429 not in answers[:10] and answers[10] == 429


def test_the_live_schema_needs_a_session(client):
    assert client.get("/api/v1/schema/").status_code == 401


def test_push_does_not_follow_redirects():
    handler = webpush._NoRedirects()
    request = urllib.request.Request("https://fcm.googleapis.com/fcm/send/abc", method="POST")
    assert handler.redirect_request(request, None, 302, "Found", {}, "http://10.0.0.1/") is None


def _settings_error(**env) -> str:
    """Load settings with production values and return what stopped it, or ""."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
    base.update({"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "x" * 50, **env})
    run = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=Path(__file__).resolve().parent.parent,
        env=base,
        capture_output=True,
        text=True,
    )
    return run.stderr


@pytest.mark.parametrize(
    "env",
    [
        {"DJANGO_ALLOWED_HOSTS": "*"},
        {"DJANGO_ALLOWED_HOSTS": ".example.com"},
        {"DJANGO_ALLOWED_HOSTS": "app.example.com", "DJANGO_CSRF_TRUSTED_ORIGINS": "http://app.example.com"},
        {"DJANGO_ALLOWED_HOSTS": "app.example.com", "DJANGO_CSRF_TRUSTED_ORIGINS": "https://*.example.com"},
    ],
)
def test_production_refuses_open_hosts_and_origins(env):
    assert "ImproperlyConfigured" in _settings_error(**env)


def test_production_takes_exact_hosts_and_https_origins():
    error = _settings_error(
        DJANGO_ALLOWED_HOSTS="app.example.com",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://app.example.com",
        REDIS_URL="redis://redis:6379/0",
    )
    assert "ImproperlyConfigured" not in error


def test_production_refuses_to_count_rate_limits_per_process():
    error = _settings_error(
        DJANGO_ALLOWED_HOSTS="app.example.com",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://app.example.com",
        REDIS_URL="",
    )
    assert "REDIS_URL is required" in error
