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


def test_the_owner_signs_in_at_the_admin(monkeypatch, client):
    run(monkeypatch)
    assert client.get("/admin").status_code == 301  # the bare address leads to the form
    wrong = client.post("/admin/login/", {"username": EMAIL, "password": "not-the-password"})
    assert wrong.status_code == 200 and "_auth_user_id" not in client.session
    response = client.post("/admin/login/?next=/admin/", {"username": EMAIL, "password": PASSWORD})
    assert response.status_code == 302 and response["Location"] == "/admin/"
    page = client.get("/admin/")
    assert page.status_code == 200 and b"Users" in page.content


def test_someone_who_is_not_staff_cannot_sign_in_at_the_admin(client):
    User.objects.create_user(email="player@example.com", password=PASSWORD)
    response = client.post("/admin/login/", {"username": "player@example.com", "password": PASSWORD})
    assert response.status_code == 200 and "_auth_user_id" not in client.session
    assert client.get("/admin/").status_code == 302


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
