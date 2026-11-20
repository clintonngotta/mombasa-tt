"""Organizers add a player before they register, invite them by email or phone, and the player joins
from the link; players log in with an email or a phone number (REQ-003)."""

import re

import pytest
from django.core import mail

from accounts.models import User
from accounts.phones import normalize_phone
from competitions.models import EntryPlayer
from guests.models import Guest, GuestClaim, GuestInvitation

from .conftest import PASSWORD, BrowserClient, link_from
from .helpers import logged_in, make_user
from .test_entries import enter
from .test_guests import guests, open_cup
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db

AUTH = "/api/v1/auth/"


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    return venue


def add_player(staff, club, expect=201, **contact) -> dict:
    """The organizer adds somebody new, with an email and/or phone to invite them at once."""
    response = staff.post(guests(club), {"display_name": "Juma", **contact}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def token_of(link: str) -> str:
    match = re.search(r"/join/([\w-]+)$", link)
    assert match, link
    return match.group(1)


def join(client, token, expect=200, **details) -> dict:
    body = {"display_name": "Juma Mwangi", "password": PASSWORD, **details}
    response = client.post(f"{AUTH}invitations/{token}/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def log_in(client, login, password=PASSWORD):
    return client.post(f"{AUTH}login/", {"login": login, "password": password}, format="json")


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("0712 345 678", "+254712345678"),
        ("712345678", "+254712345678"),
        ("254712345678", "+254712345678"),
        ("+254 712-345-678", "+254712345678"),
        ("00447700900123", "+447700900123"),
        ("12345", None),
        ("0712 345", None),
        ("+254 7123", None),
        ("phone", None),
    ],
)
def test_phone_numbers_are_stored_in_one_form(typed, stored):
    assert normalize_phone(typed) == stored


def test_organizer_adds_a_player_by_phone_and_they_join_from_the_shared_link(staff, club, hall):
    cup, event = open_cup(staff, club, hall)
    mail.outbox.clear()
    added = add_player(staff, club, phone="0712 345 678")
    assert added["invitation"]["phone"] == "+254712345678" and added["invitation"]["email"] == ""
    assert added["invite_link"].startswith("http") and not mail.outbox, "a phone invite sends no mail"
    entry = enter(staff, cup, event, player_ids=[added["id"]])
    token = token_of(added["invite_link"])
    # The link is the proof: only its hash is stored, and the list never shows it again.
    assert token not in str(GuestInvitation.objects.values_list("token_hash", flat=True)[0])
    assert "invite_link" not in staff.get(guests(club)).json()["results"][0]

    invitee = BrowserClient()
    shown = invitee.get(f"{AUTH}invitations/{token}/").json()
    assert (shown["guest_name"], shown["organization_name"], shown["phone"]) == (
        "Juma",
        club.name,
        "+254712345678",
    )
    assert [(e["tournament_name"], e["event_name"]) for e in shown["entries"]] == [(cup["name"], "Singles")]

    joined = join(invitee, token, phone="+254712345678", country="KE", region="Mombasa", city="Mombasa")
    assert joined == {"signed_in": True}
    me = invitee.get(f"{AUTH}me/").json()
    assert (me["id"], me["display_name"], me["phone"], me["email"]) == (
        added["id"],
        "Juma Mwangi",
        "+254712345678",
        None,
    )
    # The guest became the account: the entry is theirs with nothing moved.
    assert EntryPlayer.objects.get(entry_id=entry["id"]).user_id == User.objects.get(phone="+254712345678").pk
    guest = Guest.objects.get()
    assert guest.claimed_by_id == guest.user_id
    assert GuestClaim.objects.get().status == "merged"
    assert User.objects.get(pk=added["id"]).profile.city == "Mombasa"

    # They log in with the phone number, however they type it; the link works once.
    again = BrowserClient()
    assert log_in(again, "0712345678").status_code == 200
    assert BrowserClient().get(f"{AUTH}invitations/{token}/").status_code == 404
    assert join(BrowserClient(), token, expect=404, phone="0712345678")["code"] == "invitation_closed"
    # Once joined they are a player like any other: no longer offered as a guest to enter.
    assert staff.get(guests(club), {"claimed": "false"}).json()["results"] == []


def test_an_emailed_invitation_joins_with_that_email_and_logs_in_with_either(
    staff, club, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        added = add_player(staff, club, email="Juma@Example.com", phone="0722000111")
    assert mail.outbox[-1].to == ["juma@example.com"]
    assert added["invite_link"] in mail.outbox[-1].body
    token = token_of(added["invite_link"])

    invitee = BrowserClient()
    assert join(invitee, token, email="juma@example.com", phone="0722 000 111") == {"signed_in": True}
    user = User.objects.get(pk=added["id"])
    assert user.is_email_verified and user.phone_verified_at
    assert log_in(BrowserClient(), "JUMA@example.com").status_code == 200
    assert log_in(BrowserClient(), "+254722000111").status_code == 200
    assert (
        log_in(BrowserClient(), "0722000111", "wrong-password-here").json()["code"] == "invalid_credentials"
    )


def test_a_different_email_must_be_verified_before_the_account_signs_in(
    staff, club, django_capture_on_commit_callbacks
):
    added = add_player(staff, club, phone="0733000111")
    invitee = BrowserClient()
    with django_capture_on_commit_callbacks(execute=True):
        joined = join(invitee, token_of(added["invite_link"]), email="mine@example.com")
    assert joined == {"signed_in": False}
    assert invitee.get(f"{AUTH}me/").status_code == 401
    assert log_in(BrowserClient(), "mine@example.com").json()["code"] == "email_unverified"
    token = link_from(mail.outbox[-1], "/verify-email")["token"]
    assert invitee.post(f"{AUTH}verification/confirm/", {"token": token}, format="json").status_code == 200
    assert invitee.get(f"{AUTH}me/").json()["email"] == "mine@example.com"


def test_an_email_or_phone_on_another_account_is_refused_and_that_account_claims_by_link(staff, club, hall):
    cup, event = open_cup(staff, club, hall)
    existing = make_user("ama@example.com", display_name="Ama", phone="+254700000001")
    added = add_player(staff, club, phone="0700000001")
    enter(staff, cup, event, player_ids=[added["id"]])
    token = token_of(added["invite_link"])

    assert join(BrowserClient(), token, expect=409, email="ama@example.com")["code"] == "email_taken"
    assert join(BrowserClient(), token, expect=409, phone="0700000001")["code"] == "phone_taken"
    assert GuestInvitation.objects.get().status == "pending", "a refused join leaves the link usable"

    ama = logged_in(existing)
    claimed = ama.post(f"{AUTH}invitations/{token}/claim/", {}, format="json")
    assert claimed.status_code == 200 and claimed.json()["status"] == "merged"
    assert EntryPlayer.objects.get(event_id=event["id"]).user_id == existing.pk
    assert BrowserClient().post(f"{AUTH}invitations/{token}/claim/", {}, format="json").status_code == 401


def test_inviting_needs_an_email_or_phone_and_a_valid_number(staff, club):
    guest = add_player(staff, club)
    assert guest["invite_link"] is None and guest["invitation"] is None
    invite = f"{guests(club)}{guest['id']}/invite/"
    assert staff.post(invite, {}, format="json").status_code == 400
    assert "phone" in staff.post(invite, {"phone": "12"}, format="json").json()["fields"]
    first = staff.post(invite, {"phone": "0712345678"}, format="json").json()
    second = staff.post(invite, {"email": "j@example.com"}, format="json").json()
    # A new invitation replaces the old one, and the old link stops working.
    assert BrowserClient().get(f"{AUTH}invitations/{token_of(first['invite_link'])}/").status_code == 404
    assert BrowserClient().get(f"{AUTH}invitations/{token_of(second['invite_link'])}/").status_code == 200
    outsider = logged_in(make_user("out@example.com"))
    assert outsider.post(invite, {"phone": "0712345678"}, format="json").status_code == 403


def test_join_checks_the_password_and_needs_a_way_to_log_in(staff, club):
    token = token_of(add_player(staff, club, phone="0712345678")["invite_link"])
    assert "email" in join(BrowserClient(), token, expect=400)["fields"]
    assert (
        "password" in join(BrowserClient(), token, expect=400, phone="0712345678", password="short")["fields"]
    )
    assert BrowserClient().get(f"{AUTH}invitations/not-a-real-token/").status_code == 404


def test_players_add_a_phone_to_log_in_with_and_numbers_stay_unique(client):
    ama = logged_in(make_user("ama@example.com"))
    assert (
        ama.patch(f"{AUTH}me/", {"phone": "0711 222 333"}, format="json").json()["phone"] == "+254711222333"
    )
    assert log_in(BrowserClient(), "0711222333").status_code == 200
    kofi = logged_in(make_user("kofi@example.com"))
    assert kofi.patch(f"{AUTH}me/", {"phone": "+254711222333"}, format="json").json()["code"] == "phone_taken"
    assert ama.patch(f"{AUTH}me/", {"phone": ""}, format="json").json()["phone"] is None
    assert log_in(BrowserClient(), "0711222333").json()["code"] == "invalid_credentials"
    # The old field name still works for apps that send it.
    old = client.post(f"{AUTH}login/", {"email": "ama@example.com", "password": PASSWORD}, format="json")
    assert old.status_code == 200


def test_a_phone_only_account_keeps_its_phone_until_it_has_a_verified_email(staff, club):
    token = token_of(add_player(staff, club, phone="0712345678")["invite_link"])
    invitee = BrowserClient()
    join(invitee, token, phone="0712345678")
    refused = invitee.patch(f"{AUTH}me/", {"phone": "0799999999"}, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "phone_locked"
