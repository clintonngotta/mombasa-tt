"""A player who was added by phone adds an email address (REQ-003): a link goes to the address, nothing
changes until it is opened, and the answer never tells whether the address belongs to someone else."""

import re
from urllib.parse import unquote

import pytest
from django.core import mail
from django.core.cache import cache

from accounts.models import User

from .conftest import BrowserClient
from .helpers import make_user
from .test_player_invites import AUTH, add_player, join, log_in, token_of

pytestmark = pytest.mark.django_db
ADD = f"{AUTH}me/email/"


def link_token(message) -> str:
    return unquote(re.search(r"token=([^&\s]+)", message.body).group(1))


@pytest.fixture
def phone_player(staff, club):
    """Somebody the organizer added by phone, who joined from the link with a phone and no email."""
    token = token_of(add_player(staff, club, phone="0712345678")["invite_link"])
    client = BrowserClient()
    join(client, token, phone="0712345678")
    assert client.get(f"{AUTH}me/").json()["email"] is None
    mail.outbox.clear()
    cache.clear()
    return client


def test_a_phone_account_adds_an_email_and_then_logs_in_with_either(phone_player):
    sent = phone_player.post(ADD, {"email": "Juma@Example.com"}, format="json")
    assert sent.status_code == 202
    # Nothing changes until the link is opened.
    assert phone_player.get(f"{AUTH}me/").json()["email"] is None
    assert [m.to for m in mail.outbox] == [["juma@example.com"]]
    confirmed = BrowserClient().post(
        f"{AUTH}verification/confirm/", {"token": link_token(mail.outbox[0])}, format="json"
    )
    assert confirmed.status_code == 200 and confirmed.json()["email"] == "juma@example.com"
    me = phone_player.get(f"{AUTH}me/").json()
    assert me["email"] == "juma@example.com" and me["email_verified_at"] and me["phone"] == "+254712345678"
    assert log_in(BrowserClient(), "juma@example.com").status_code == 200
    assert log_in(BrowserClient(), "0712345678").status_code == 200
    # Once confirmed, the account has its email: adding another this way is refused.
    assert phone_player.post(ADD, {"email": "other@example.com"}, format="json").json()["code"] == "email_set"


def test_an_address_on_another_account_gets_the_same_answer_and_is_never_taken(phone_player):
    owner = make_user("owner@example.com", display_name="Owner")
    taken = phone_player.post(ADD, {"email": "owner@example.com"}, format="json")
    free = phone_player.post(ADD, {"email": "free@example.com"}, format="json")
    assert (taken.status_code, taken.json()) == (free.status_code, free.json()) == (202, free.json())
    # The owner hears about it; no confirmation link for their address exists.
    to_owner = [m for m in mail.outbox if m.to == ["owner@example.com"]]
    assert len(to_owner) == 1 and "verify-email?token=" not in to_owner[0].body
    assert User.objects.get(pk=owner.pk).email == "owner@example.com"
    assert phone_player.get(f"{AUTH}me/").json()["email"] is None

    # An address someone else takes before the link is opened stays theirs.
    token = link_token(next(m for m in mail.outbox if m.to == ["free@example.com"]))
    make_user("free@example.com", display_name="Quicker")
    late = BrowserClient().post(f"{AUTH}verification/confirm/", {"token": token}, format="json")
    assert late.status_code == 400 and late.json()["code"] == "invalid_token"
    assert phone_player.get(f"{AUTH}me/").json()["email"] is None


def test_adding_an_email_needs_a_login_a_valid_address_and_is_rate_limited(phone_player):
    assert BrowserClient().post(ADD, {"email": "x@example.com"}, format="json").status_code in (401, 403)
    assert phone_player.post(ADD, {"email": "not-an-email"}, format="json").status_code == 400
    assert phone_player.post(ADD, {}, format="json").status_code == 400
    # A token for one purpose doesn't work as the other, and a made-up one is refused.
    bad = BrowserClient().post(f"{AUTH}verification/confirm/", {"token": "abc"}, format="json")
    assert bad.status_code == 400
    cache.clear()
    codes = [
        phone_player.post(ADD, {"email": f"a{n}@example.com"}, format="json").status_code for n in range(8)
    ]
    assert 429 in codes
