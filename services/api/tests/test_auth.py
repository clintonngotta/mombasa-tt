import pytest
from rest_framework.test import APIClient

from accounts.models import User

from .conftest import PASSWORD, BrowserClient, link_from

pytestmark = pytest.mark.django_db


def signup(client, email="kofi@example.com", password=PASSWORD):
    return client.post(
        "/api/v1/auth/signup/", {"display_name": "Kofi", "email": email, "password": password}, format="json"
    )


def test_signup_creates_unverified_user_and_sends_verification(client, mailoutbox):
    res = signup(client, email="Kofi@Example.com")
    assert res.status_code == 201
    user = User.objects.get(email="kofi@example.com")
    assert not user.is_email_verified
    assert "/verify-email?" in mailoutbox[0].body


def test_signup_with_existing_email_looks_identical_and_creates_nothing(client, verified_user, mailoutbox):
    res = signup(client, email="AMA@example.com")
    assert res.status_code == 201
    assert res.json() == signup(BrowserClient(), email="new@example.com").json()
    assert User.objects.filter(email="ama@example.com").count() == 1
    assert "already have a mombasa-tt account" in mailoutbox[0].subject


def test_signup_rejects_weak_password_with_field_error(client):
    res = signup(client, password="short")
    assert res.status_code == 400
    body = res.json()
    assert body["code"] == "validation_error"
    assert "password" in body["fields"]
    assert body["request_id"] == res["X-Request-ID"]


def test_verify_link_verifies_and_logs_in(client, mailoutbox):
    signup(client)
    token = link_from(mailoutbox[0], "/verify-email")["token"]
    res = client.post("/api/v1/auth/verification/confirm/", {"token": token}, format="json")
    assert res.status_code == 200
    assert res.json()["email_verified_at"]
    assert client.get("/api/v1/auth/me/").json()["email"] == "kofi@example.com"


def test_tampered_verify_token_is_rejected(client):
    res = client.post("/api/v1/auth/verification/confirm/", {"token": "nope"}, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_token"


def test_wrong_password_and_unknown_email_get_identical_responses(client, verified_user):
    wrong = client.post(
        "/api/v1/auth/login/", {"email": "ama@example.com", "password": "x" * 12}, format="json"
    )
    unknown = client.post(
        "/api/v1/auth/login/", {"email": "who@example.com", "password": "x" * 12}, format="json"
    )
    assert wrong.status_code == unknown.status_code == 400
    strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert strip(wrong) == strip(unknown)


def test_unverified_user_told_only_after_correct_password(client):
    signup(client)
    wrong = client.post(
        "/api/v1/auth/login/", {"email": "kofi@example.com", "password": "x" * 12}, format="json"
    )
    right = client.post(
        "/api/v1/auth/login/", {"email": "kofi@example.com", "password": PASSWORD}, format="json"
    )
    assert wrong.json()["code"] == "invalid_credentials"
    assert right.status_code == 403
    assert right.json()["code"] == "email_unverified"


def test_login_me_logout(client, verified_user):
    assert client.get("/api/v1/auth/me/").status_code == 401
    res = client.post(
        "/api/v1/auth/login/", {"email": "AMA@example.com", "password": PASSWORD}, format="json"
    )
    assert res.status_code == 200
    assert client.get("/api/v1/auth/me/").json()["display_name"] == "Ama"
    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 401


def test_login_requires_csrf_token(verified_user):
    raw = APIClient(enforce_csrf_checks=True)
    res = raw.post("/api/v1/auth/login/", {"email": "ama@example.com", "password": PASSWORD}, format="json")
    assert res.status_code == 403
    assert res.json()["code"] == "csrf_failed"


def test_session_cookie_is_httponly(client, verified_user):
    client.post("/api/v1/auth/login/", {"email": "ama@example.com", "password": PASSWORD}, format="json")
    assert client.cookies["sessionid"]["httponly"]


def test_password_reset_is_non_enumerating_and_ends_other_sessions(client, verified_user, mailoutbox):
    other_device = BrowserClient()
    other_device.post(
        "/api/v1/auth/login/", {"email": "ama@example.com", "password": PASSWORD}, format="json"
    )
    assert other_device.get("/api/v1/auth/me/").status_code == 200

    known = client.post("/api/v1/auth/password-reset/", {"email": "ama@example.com"}, format="json")
    unknown = client.post("/api/v1/auth/password-reset/", {"email": "who@example.com"}, format="json")
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(mailoutbox) == 1

    params = link_from(mailoutbox[0], "/reset-password")
    new_password = "a-brand-new-passphrase"
    res = client.post(
        "/api/v1/auth/password-reset/confirm/", {**params, "password": new_password}, format="json"
    )
    assert res.status_code == 204
    assert other_device.get("/api/v1/auth/me/").status_code == 401

    reused = client.post(
        "/api/v1/auth/password-reset/confirm/", {**params, "password": "another-passphrase-1"}, format="json"
    )
    assert reused.json()["code"] == "invalid_token"
    login = client.post(
        "/api/v1/auth/login/", {"email": "ama@example.com", "password": new_password}, format="json"
    )
    assert login.status_code == 200


def test_login_is_throttled(client, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth_login": "3/min", "auth_email": "3/min"})
    codes = [
        client.post(
            "/api/v1/auth/login/", {"email": "a@example.com", "password": "x" * 12}, format="json"
        ).status_code
        for _ in range(4)
    ]
    assert codes == [400, 400, 400, 429]


def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json()["checks"]["database"] == "ok"
