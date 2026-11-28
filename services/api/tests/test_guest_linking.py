"""Joining a guest to the account of the player behind it (REQ-003, EVAL-003): a player who joins on their
own later still finds what they played as a guest, staff can ask a player found in the directory, and
staff can make a fresh link. Names are never matched; nothing moves until the player accepts."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from competitions.models import EntryPlayer
from guests.models import GuestInvitation

from .helpers import logged_in, make_user
from .test_entries import enter
from .test_guests import accept, guests, hall, invite, new_guest, open_cup  # noqa: F401
from .test_invite_player import listed

pytestmark = pytest.mark.django_db

MINE = "/api/v1/me/guest-invitations/"


def test_a_player_who_joins_after_the_link_lapsed_still_finds_their_matches(staff, club, hall):  # noqa: F811
    cup, event = open_cup(staff, club, hall)
    guest = new_guest(staff, club)
    entry = enter(staff, cup, event, player_ids=[guest["id"]])
    invite(staff, club, guest, "juma@example.com")
    GuestInvitation.objects.update(expires_at=timezone.now() - timedelta(days=1))  # never opened

    # They sign up on their own, weeks later, with the address staff had: their inbox has it.
    juma = make_user("Juma@Example.com", display_name="Juma Mwangi")
    claim = accept(logged_in(juma))
    assert claim["status"] == "merged"
    assert EntryPlayer.objects.get(entry_id=entry["id"]).user_id == juma.id

    # Nobody else with a similar name, and no unverified owner of the address, is offered it.
    other = new_guest(staff, club, "Juma")
    invite(staff, club, other, "someone@example.com")
    assert logged_in(make_user("juma2@example.com", display_name="Juma")).get(MINE).json()["results"] == []


def test_staff_ask_a_listed_player_whether_they_are_the_guest(
    staff,
    club,
    hall,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    cup, event = open_cup(staff, club, hall)
    guest = new_guest(staff, club)
    entry = enter(staff, cup, event, player_ids=[guest["id"]])
    amina = listed(make_user("amina@example.com", display_name="Amina"))

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        response = staff.post(
            f"{guests(club)}{guest['id']}/link-player/", {"player_id": str(amina.id)}, format="json"
        )
    assert response.status_code == 201, response.json()
    shown = response.json()["invitation"]
    # Staff see the name they chose, never the player's address.
    assert (shown["invitee_name"], shown["email"], shown["phone"]) == ("Amina", "", "")
    assert mail.outbox[-1].to == ["amina@example.com"] and "/profile/claims" in mail.outbox[-1].body

    # Nothing has moved until she accepts; then the entry is hers.
    assert EntryPlayer.objects.get(entry_id=entry["id"]).user_id != amina.id
    assert accept(logged_in(amina))["status"] == "merged"
    assert EntryPlayer.objects.get(entry_id=entry["id"]).user_id == amina.id
    trail = staff.get(f"/api/v1/organizations/{club.id}/guest-claims/").json()["results"][0]
    assert (trail["invited_player_name"], trail["invited_email"]) == ("Amina", "")


def test_only_listed_players_can_be_asked_and_only_they_see_it(staff, club):
    guest = new_guest(staff, club)
    hidden = make_user("hidden@example.com")  # not in the directory
    path = f"{guests(club)}{guest['id']}/link-player/"
    for player_id in (str(hidden.id), "7d1b8c5e-0000-4000-8000-000000000000", guest["id"]):
        response = staff.post(path, {"player_id": player_id}, format="json")
        assert response.status_code == 400, response.json()
    assert staff.post(path, {"player_id": "nope"}, format="json").status_code == 400
    assert not GuestInvitation.objects.exists()

    asked = listed(make_user("asked@example.com"))
    assert staff.post(path, {"player_id": str(asked.id)}, format="json").status_code == 201
    pending = GuestInvitation.objects.get()
    for someone in (make_user("other@example.com"), hidden):
        client = logged_in(someone)
        assert client.get(MINE).json()["results"] == []
        assert client.post(f"{MINE}{pending.id}/accept/", {}, format="json").status_code == 404
    # A member of another club, or of this one without the right, can't ask anyone.
    outsider = logged_in(make_user("outsider@example.com"))
    assert outsider.post(path, {"player_id": str(asked.id)}, format="json").status_code in (403, 404)

    # A request to a player lapses like any invitation; declining leaves the guest as it was.
    client = logged_in(asked)
    assert client.post(f"{MINE}{pending.id}/decline/", {}, format="json").status_code == 204
    assert GuestInvitation.objects.get().status == "declined"


def test_staff_make_a_fresh_link_from_the_guest_list(staff, club, django_capture_on_commit_callbacks):
    guest = new_guest(staff, club)
    path = f"{guests(club)}{guest['id']}/new-link/"

    # A guest never invited gets a link with no address, to share by hand.
    first = staff.post(path, {}, format="json")
    assert first.status_code == 201, first.json()
    assert first.json()["invite_link"] and first.json()["invitation"]["email"] == ""

    # After an email invitation, the fresh link keeps the address and phone but sends nothing.
    staff.post(
        f"{guests(club)}{guest['id']}/invite/",
        {"email": "juma@example.com", "phone": "0712345678"},
        format="json",
    )
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        fresh = staff.post(path, {}, format="json").json()
    assert mail.outbox == []
    assert (fresh["invitation"]["email"], fresh["invitation"]["phone"]) == (
        "juma@example.com",
        "+254712345678",
    )
    assert GuestInvitation.objects.filter(status="pending").count() == 1
    old_link = first.json()["invite_link"]
    old_token = old_link.rsplit("/", 1)[-1]
    assert staff.get(f"/api/v1/auth/invitations/{old_token}/").status_code == 404, "the old link is dead"
    new_token = fresh["invite_link"].rsplit("/", 1)[-1]
    assert staff.get(f"/api/v1/auth/invitations/{new_token}/").status_code == 200

    # Only the club's guest staff can make one.
    outsider = logged_in(make_user("outsider@example.com"))
    assert outsider.post(path, {}, format="json").status_code in (403, 404)
