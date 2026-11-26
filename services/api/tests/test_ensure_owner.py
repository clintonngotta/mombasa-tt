"""The owner account made at start from OWNER_EMAIL and OWNER_PASSWORD (deployment.md)."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User

pytestmark = pytest.mark.django_db
EMAIL = "owner@example.org"
PASSWORD = "a-long-owner-passphrase-41"


def run(monkeypatch, email=EMAIL, password=PASSWORD):
    for key, value in (("OWNER_EMAIL", email), ("OWNER_PASSWORD", password)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    out = StringIO()
    call_command("ensure_owner", stdout=out)
    return out.getvalue()


def test_the_owner_is_created_as_a_verified_super_admin_who_can_log_in(monkeypatch, client):
    out = run(monkeypatch)
    owner = User.objects.get(email=EMAIL)
    assert owner.is_superuser and owner.is_staff and owner.is_active and owner.is_email_verified
    assert PASSWORD not in out
    response = client.post(
        "/api/v1/auth/login/", {"login": EMAIL, "password": PASSWORD}, content_type="application/json"
    )
    assert response.status_code == 200


def test_the_owner_reaches_the_back_office(monkeypatch, client):
    run(monkeypatch)
    signed_in = client.post(
        "/api/v1/auth/login/", {"login": EMAIL, "password": PASSWORD}, content_type="application/json"
    )
    assert signed_in.json()["is_platform_admin"] is True
    assert client.get("/api/v1/platform/overview/").status_code == 200


def test_admin_is_the_apps_own_page_not_django(client):
    assert client.get("/admin").status_code == 404  # the proxy serves the app there, never the API
    assert client.get("/admin/").status_code == 404
    assert client.get("/admin/login/").status_code == 404


def test_nothing_happens_without_the_settings(monkeypatch):
    run(monkeypatch, None, None)
    assert not User.objects.filter(is_superuser=True).exists()


def test_a_later_start_keeps_the_password_the_owner_chose(monkeypatch):
    run(monkeypatch)
    owner = User.objects.get(email=EMAIL)
    owner.set_password("changed-in-the-app-77-zebra")
    owner.save()
    run(monkeypatch)
    owner.refresh_from_db()
    assert owner.check_password("changed-in-the-app-77-zebra")
    assert User.objects.filter(email=EMAIL).count() == 1


def test_a_later_start_restores_lost_authority(monkeypatch):
    run(monkeypatch)
    User.objects.filter(email=EMAIL).update(is_superuser=False, is_active=False)
    run(monkeypatch)
    owner = User.objects.get(email=EMAIL)
    assert owner.is_superuser and owner.is_active


@pytest.mark.parametrize(
    "email, password",
    [(EMAIL, "password"), (EMAIL, None), (None, PASSWORD), ("not-an-email", PASSWORD)],
)
def test_bad_settings_stop_the_start_and_make_no_account(monkeypatch, email, password):
    with pytest.raises(CommandError) as error:
        run(monkeypatch, email, password)
    assert PASSWORD not in str(error.value)
    assert not User.objects.exists()
