"""Guests entered by club staff, and claiming them (REQ-003, EVAL-003)."""

import pytest
from django.core import mail

from accounts.models import User
from competitions.models import EntryPlayer, Match
from guests.models import Guest, GuestClaim, GuestInvitation

from .conftest import PASSWORD, BrowserClient
from .helpers import logged_in, make_user
from .test_draws import draw_url
from .test_entries import act, enter
from .test_reservations import person
from .test_roles import create_club
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db

ORGS = "/api/v1/organizations/"


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    return venue


def guests(club) -> str:
    return f"{ORGS}{club.id}/guests/"


def claims(club) -> str:
    return f"{ORGS}{club.id}/guest-claims/"


def new_guest(staff, club, name="Juma") -> dict:
    response = staff.post(guests(club), {"display_name": name}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def invite(staff, club, guest, email="juma@example.com", expect=201) -> dict:
    response = staff.post(f"{guests(club)}{guest['id']}/invite/", {"email": email}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def open_cup(staff, club, hall):
    cup = add_event(staff, make_tournament(staff, club, hall), name="Singles")
    cup = do(staff, cup, "publish")
    return cup, cup["events"][0]


def play(staff, cup, event, *entries) -> Match:
    """Check the entries in, publish the draw and start: the guest has a match."""
    for entry in entries:
        staff.post(url(cup, event=event) + f"entries/{entry['id']}/check-in/", {}, format="json")
    staff.post(draw_url(cup, event, "preview"), {"rng_seed": 1}, format="json")
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200
    do(staff, cup, "start")
    do(staff, cup, "start", event=event)
    return Match.objects.get(draw__event_id=event["id"])


def accept(client, expect=200) -> dict:
    mine = client.get("/api/v1/me/guest-invitations/").json()["results"]
    assert len(mine) == 1, mine
    response = client.post(f"/api/v1/me/guest-invitations/{mine[0]['id']}/accept/", {}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_staff_create_guests_nobody_can_sign_in_as(staff, club):
    made = new_guest(staff, club)
    assert (made["display_name"], made["invitation"], made["claimed_at"], made["entries"]) == (
        "Juma",
        None,
        None,
        0,
    )
    user = User.objects.get(pk=made["id"])
    assert not user.has_usable_password()
    assert not user.can_receive_email and not user.email_verified_at
    assert user.email.endswith("@guests.invalid")
    assert (
        staff.patch(f"{guests(club)}{made['id']}/", {"display_name": "Juma M."}, format="json").json()[
            "display_name"
        ]
        == "Juma M."
    )
    assert [g["id"] for g in staff.get(guests(club), {"search": "juma"}).json()["results"]] == [made["id"]]
    outsider = logged_in(make_user("outsider@example.com"))
    assert outsider.get(guests(club)).status_code == 403
    assert outsider.post(guests(club), {"display_name": "X"}, format="json").status_code == 403


def test_only_the_hosts_staff_enter_its_own_guests_and_guests_get_no_mail(staff, club, hall, admin):
    cup, event = open_cup(staff, club, hall)
    guest = new_guest(staff, club)
    mail.outbox.clear()
    entry = enter(staff, cup, event, player_ids=[guest["id"]])
    assert (
        EntryPlayer.objects.get(entry_id=entry["id"]).user_id
        == Guest.objects.get(user__display_name="Juma").user_id
    )
    assert not [m for m in mail.outbox if any(to.endswith("guests.invalid") for to in m.to)]
    assert staff.get(guests(club)).json()["results"][0]["entries"] == 1
    # A player can't enter a guest with themselves, and another club's guest isn't the host's.
    player = logged_in(make_user("player@example.com"))
    other = new_guest(staff, club, "Other")
    reply = enter(player, cup, event, expect=400, player_ids=[other["id"]])
    assert "player_ids" in reply["fields"]
    elsewhere = create_club(admin, name="Kilifi TT")
    theirs = new_guest(staff, elsewhere, "Theirs")
    assert "player_ids" in enter(staff, cup, event, expect=400, player_ids=[theirs["id"]])["fields"]


def test_a_verified_invitee_claims_the_guest_and_keeps_its_matches(
    staff, club, hall, django_capture_on_commit_callbacks
):
    cup, event = open_cup(staff, club, hall)
    guest = new_guest(staff, club)
    mine = enter(staff, cup, event, player_ids=[guest["id"]])
    theirs = enter(staff, cup, event, player_ids=[str(person("Brian").id)])
    match = play(staff, cup, event, mine, theirs)

    mail.outbox.clear()
    first = invite(staff, club, guest, "old@example.com")
    with django_capture_on_commit_callbacks(execute=True):
        shown = invite(staff, club, guest)
    assert shown["invitation"]["email"] == "juma@example.com"
    assert GuestInvitation.objects.get(email="old@example.com").status == "revoked", "a new one replaces it"
    assert mail.outbox[-1].to == ["juma@example.com"] and "Juma" in mail.outbox[-1].body
    assert first["invitation"]["email"] == "old@example.com"

    # Only a signed-in account with that verified address sees it.
    unverified = BrowserClient()  # signing in needs a verified address, so the session is made directly
    unverified.force_login(User.objects.create_user("juma@example.com", PASSWORD, display_name="Juma"))
    assert unverified.get("/api/v1/me/guest-invitations/").json()["results"] == []
    User.objects.filter(email="juma@example.com").delete()
    stranger = logged_in(make_user("stranger@example.com"))
    pending = GuestInvitation.objects.get(status="pending")
    assert (
        stranger.post(f"/api/v1/me/guest-invitations/{pending.id}/accept/", {}, format="json").status_code
        == 404
    )

    juma = make_user("juma@example.com", display_name="Juma Mwangi")
    claimant = logged_in(juma)
    claim = accept(claimant)
    assert (claim["status"], claim["guest_name"], claim["clashes"]) == ("merged", "Juma", [])
    # The same rows, now the claimant's: the match still refers to the same entry and player.
    assert EntryPlayer.objects.get(entry_id=mine["id"]).user_id == juma.id
    assert str(Match.objects.get(pk=match.pk).id) == str(match.id)
    stale = User.objects.get(pk=guest["id"])
    assert not stale.is_active and not EntryPlayer.objects.filter(user=stale).exists()
    shown = staff.get(guests(club), {"claimed": "true"}).json()["results"][0]
    assert (shown["claimed_by_name"], shown["entries"]) == ("Juma Mwangi", 0)
    # Single use: the invitation is gone, and a claimed guest can't be invited or entered again.
    assert claimant.get("/api/v1/me/guest-invitations/").json()["results"] == []
    assert (
        claimant.post(f"/api/v1/me/guest-invitations/{pending.id}/accept/", {}, format="json").status_code
        == 404
    )
    assert invite(staff, club, guest, expect=409)["code"] == "guest_claimed"
    assert [c["status"] for c in claimant.get("/api/v1/me/guest-claims/").json()["results"]] == ["merged"]
    trail = staff.get(claims(club)).json()["results"][0]["events"]
    assert [e["action"] for e in trail] == ["accepted", "merged"]


def test_a_clash_moves_nothing_until_staff_resolve_it(staff, club, hall):
    cup, event = open_cup(staff, club, hall)
    guest = new_guest(staff, club)
    juma = make_user("juma@example.com", display_name="Juma Mwangi")
    as_guest = enter(staff, cup, event, player_ids=[guest["id"]])
    own = enter(staff, cup, event, player_ids=[str(juma.id)])  # entered twice under two identities

    invite(staff, club, guest)
    player = logged_in(juma)
    claim = accept(player)
    assert claim["status"] == "conflict"
    assert claim["clashes"] == ["Both are entered in the same event"]
    assert EntryPlayer.objects.get(entry_id=as_guest["id"]).user_id == Guest.objects.get().user_id
    assert invite(staff, club, guest, expect=409)["code"] == "claim_open"

    waiting = staff.get(claims(club), {"status": "conflict"}).json()["results"]
    assert [(c["guest_name"], c["invited_email"]) for c in waiting] == [("Juma", "juma@example.com")]
    path = f"{claims(club)}{waiting[0]['id']}/"
    assert staff.post(path + "retry/", {}, format="json").status_code == 400, "a note is required"
    still = staff.post(path + "retry/", {"note": "Checked"}, format="json").json()
    assert still["status"] == "conflict"
    # The player withdraws the duplicate entry, then staff try again and the move goes through.
    act(player, cup, event, own, "withdraw")
    done = staff.post(path + "retry/", {"note": "Juma withdrew the duplicate entry"}, format="json").json()
    assert done["status"] == "merged" and done["resolved_at"]
    assert [(e["action"], e["note"]) for e in done["events"]] == [
        ("accepted", ""),
        ("conflict", "Both are entered in the same event"),
        ("retried", "Checked"),
        ("retried", "Juma withdrew the duplicate entry"),
        ("merged", ""),
    ]
    assert EntryPlayer.objects.get(entry_id=as_guest["id"]).user_id == juma.id
    assert staff.post(path + "reject/", {"note": "x"}, format="json").json()["code"] == "claim_settled"


def test_staff_can_reject_a_claim_and_the_guest_stays_as_it_was(staff, club, hall):
    cup, event = open_cup(staff, club, hall)
    guest = new_guest(staff, club)
    juma = make_user("juma@example.com")
    enter(staff, cup, event, player_ids=[guest["id"]])
    enter(staff, cup, event, player_ids=[str(juma.id)])
    invite(staff, club, guest)
    accept(logged_in(juma))
    claim = GuestClaim.objects.get()
    outsider = logged_in(make_user("outsider@example.com"))
    assert (
        outsider.post(f"{claims(club)}{claim.id}/reject/", {"note": "no"}, format="json").status_code == 403
    )
    rejected = staff.post(
        f"{claims(club)}{claim.id}/reject/", {"note": "Two different players"}, format="json"
    )
    assert rejected.json()["status"] == "rejected"
    assert Guest.objects.get().claimed_by is None and User.objects.get(pk=guest["id"]).is_active
    # Names are never matched: a new invitation is the only way on.
    assert invite(staff, club, guest, "someone@example.com")["invitation"]["email"] == "someone@example.com"


def test_an_invitation_can_be_revoked_or_declined(staff, club):
    guest = new_guest(staff, club)
    invite(staff, club, guest)
    revoked = staff.post(f"{guests(club)}{guest['id']}/revoke-invitation/", {}, format="json")
    assert revoked.json()["invitation"] is None
    again = staff.post(f"{guests(club)}{guest['id']}/revoke-invitation/", {}, format="json")
    assert again.json()["code"] == "no_invitation"
    invite(staff, club, guest)
    juma = logged_in(make_user("juma@example.com"))
    pending = juma.get("/api/v1/me/guest-invitations/").json()["results"][0]
    assert pending["organization_name"] == club.name and pending["guest_name"] == "Juma"
    assert (
        juma.post(f"/api/v1/me/guest-invitations/{pending['id']}/decline/", {}, format="json").status_code
        == 204
    )
    assert GuestInvitation.objects.get(pk=pending["id"]).status == "declined"
    assert not GuestClaim.objects.exists()


def test_a_rated_guest_is_rated_again_as_the_claimant(staff, club):
    from guests import merge
    from outbox.models import Job
    from ratings.models import Rating

    guest = new_guest(staff, club)
    Rating.objects.create(user_id=guest["id"], discipline="singles", rating=1600, played=3, won=2)
    invite(staff, club, guest)
    assert accept(logged_in(make_user("juma@example.com")))["status"] == "merged"
    assert not Rating.objects.filter(user_id=guest["id"]).exists()
    job = Job.objects.get(kind=merge.RERATE)
    merge.rerate(job.payload)  # what the worker runs: the ledgers again from the official results


def test_a_claim_moves_every_column_that_holds_a_user_hidden_ones_included():
    """Captains, rubber players and the like are declared with related_name="+", which Django's own list
    of relations leaves out. Every user column outside the guest's record and the ratings is moved."""
    from django.apps import apps

    from guests import merge

    moved = set(merge._references())
    for model in apps.get_models(include_auto_created=True):
        if model._meta.app_label in merge.SKIPPED or model in merge.RECOMPUTED:
            continue
        for field in model._meta.concrete_fields:
            if field.is_relation and field.related_model is User:
                assert (model, field.name) in moved, f"{model._meta.label}.{field.name} is not moved"
    from competitions.models import Entry, RubberPlayer

    assert (Entry, "captain") in moved and (RubberPlayer, "user") in moved
