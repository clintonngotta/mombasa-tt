"""An old cached web app is asked to update, never served half-working (REQ-035, EVAL-035)."""

import pytest

pytestmark = pytest.mark.django_db

CSRF = "/api/v1/auth/csrf/"


def test_every_build_is_served_until_a_minimum_is_set(client, settings):
    settings.MIN_CLIENT_BUILD = 0
    assert client.get(CSRF, HTTP_X_CLIENT_BUILD="1").status_code == 204


def test_a_build_older_than_the_minimum_is_told_to_update(client, settings):
    settings.MIN_CLIENT_BUILD = 202611191200
    old = client.get(CSRF, HTTP_X_CLIENT_BUILD="202611011200")
    assert old.status_code == 426
    body = old.json()
    assert body["code"] == "client_outdated"
    assert "stays on your device" in body["message"]
    assert body["request_id"] == old["X-Request-ID"]
    for build in ("202611191200", "202612010900"):
        assert client.get(CSRF, HTTP_X_CLIENT_BUILD=build).status_code == 204


def test_clients_without_a_build_and_pages_outside_the_api_are_let_through(client, settings):
    settings.MIN_CLIENT_BUILD = 202611191200
    assert client.get(CSRF).status_code == 204
    assert client.get(CSRF, HTTP_X_CLIENT_BUILD="not-a-number").status_code == 204
    assert client.get("/health/live", HTTP_X_CLIENT_BUILD="1").status_code == 200


def test_a_refused_write_changes_nothing(client, settings):
    from django.contrib.auth import get_user_model

    settings.MIN_CLIENT_BUILD = 202611191200
    reply = client.post(
        "/api/v1/auth/signup/",
        {"email": "late@example.com", "password": "a-long-enough-password-1", "display_name": "Late"},
        content_type="application/json",
        HTTP_X_CLIENT_BUILD="202601010000",
    )
    assert reply.status_code == 426
    assert not get_user_model().objects.filter(email="late@example.com").exists()
