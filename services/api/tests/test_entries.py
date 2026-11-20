"""Entries, waiting list, acceptance, withdrawal and check-in (REQ-008, EVAL-008, TASK-018)."""

import threading
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from competitions.models import Entry, EntryPlayer, Event

from .helpers import logged_in, make_user
from .test_roles import ORGS
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
ME = "/api/v1/me/entries/"


def entries_url(tournament, event, entry=None, action=""):
    path = url(tournament, event=event) + "entries/"
    if entry:
        path += f"{entry['id']}/{action}/"
    return path


def player(name: str):
    return make_user(f"{name.lower()}@example.com", display_name=name)


def enter(client, tournament, event, expect=201, **body) -> dict:
    response = client.post(entries_url(tournament, event), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def act(client, tournament, event, entry, action, expect=200, **body) -> dict:
    response = client.post(entries_url(tournament, event, entry, action), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def listed(client, tournament, event, query="") -> list[dict]:
    response = client.get(entries_url(tournament, event) + query)
    assert response.status_code == 200, response.json()
    return response.json()["results"]


def names(entry) -> list[str]:
    return [p["display_name"] for p in entry["players"]]


@pytest.fixture
def cup(staff, club):
    """A published tournament with a singles, a doubles and a team event."""
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, name="Singles", capacity=2, entry_fee={"amount_minor": 50000})
    add_event(staff, tournament, name="Doubles", kind="doubles")
    add_event(staff, tournament, name="Teams", kind="team", format="round_robin")
    return do(staff, tournament, "publish")


@pytest.fixture
def singles(cup):
    return cup["events"][0]


@pytest.fixture
def doubles(cup):
    return cup["events"][1]


@pytest.fixture
def teams(cup):
    return cup["events"][2]


def test_a_player_enters_and_staff_accept(staff, cup, singles):
    ama, kofi = player("Ama"), player("Kofi")
    entry = enter(logged_in(ama), cup, singles)
    assert entry["status"] == "pending" and names(entry) == ["Ama"] and entry["mine"] is True
    assert entry["checked_in_at"] is None and entry["team_name"] == "" and entry["captain_id"] is None
    # Nothing in an entry speaks about money: accepted is a place, not a payment.
    assert not [key for key in entry if "paid" in key or "fee" in key or "payment" in key]

    # Until staff accept it, it is there for its player and staff only.
    assert listed(logged_in(kofi), cup, singles) == []
    assert [e["id"] for e in listed(logged_in(ama), cup, singles)] == [entry["id"]]
    assert [e["status"] for e in listed(staff, cup, singles)] == ["pending"]

    mail.outbox.clear()
    accepted = act(staff, cup, singles, entry, "accept")
    assert accepted["status"] == "accepted" and accepted["mine"] is False and accepted["decided_at"]
    assert [m.to for m in mail.outbox] == [[ama.email]]
    assert "accepted" in mail.outbox[0].subject and "entry fee" in mail.outbox[0].body

    seen = listed(logged_in(kofi), cup, singles)
    assert [names(e) for e in seen] == [["Ama"]] and seen[0]["mine"] is False
    assert set(seen[0]) == {
        "id",
        "status",
        "players",
        "team_name",
        "pool",
        "captain_id",
        "reason",
        "created_at",
        "decided_at",
        "withdrawn_at",
        "checked_in_at",
        "my_check_in_at",
        "mine",
    }
    assert set(seen[0]["players"][0]) == {"id", "display_name"}
    event = logged_in(kofi).get(url(cup)).json()["events"][0]
    assert event["accepted_count"] == 1 and event["capacity"] == 2

    mine = logged_in(ama).get(ME).json()["results"]
    assert [(e["event"]["name"], e["tournament"]["name"], e["status"]) for e in mine] == [
        ("Singles", "Coast Open", "accepted")
    ]
    assert logged_in(kofi).get(ME).json()["results"] == []


def test_open_admission_accepts_up_to_capacity_and_waitlists_overflow(staff, cup, singles):
    changed = staff.patch(url(cup, event=singles), {"admission": "open"}, format="json")
    assert changed.status_code == 200 and changed.json()["events"][0]["admission"] == "open"
    clients = [logged_in(player(name)) for name in ("Ama", "Kofi", "Esi")]
    first, second, overflow = (enter(client, cup, singles) for client in clients)
    assert [entry["status"] for entry in (first, second, overflow)] == [
        "accepted",
        "accepted",
        "waitlisted",
    ]
    assert first["decided_at"] and overflow["decided_at"]
    assert Entry.objects.get(pk=first["id"]).decided_by_id is None
    act(clients[0], cup, singles, first, "withdraw")
    assert Entry.objects.get(pk=overflow["id"]).status == "waitlisted"
    assert act(staff, cup, singles, overflow, "accept")["status"] == "accepted"


def test_self_check_in_requires_the_event_day_and_checks_in_each_doubles_player(staff, cup, doubles):
    from competitions.models import Tournament

    ama, kofi, esi = (player(name) for name in ("Ama", "Kofi", "Esi"))
    pair = enter(staff, cup, doubles, player_ids=[str(ama.id), str(kofi.id)])
    assert act(logged_in(esi), cup, doubles, pair, "self-check-in", expect=404)
    expected = act(logged_in(ama), cup, doubles, pair, "self-check-in", expect=409)
    assert expected["code"] == "check_in_not_today"
    tournament_day = timezone.localdate()
    Tournament.objects.filter(pk=cup["id"]).update(starts_on=tournament_day, ends_on=tournament_day)
    partial = act(logged_in(ama), cup, doubles, pair, "self-check-in")
    assert partial["my_check_in_at"] and not partial["checked_in_at"]
    assert (
        act(logged_in(ama), cup, doubles, pair, "self-check-in")["my_check_in_at"]
        == partial["my_check_in_at"]
    )
    full = act(logged_in(kofi), cup, doubles, pair, "self-check-in")
    assert full["my_check_in_at"] and full["checked_in_at"]
    assert act(staff, cup, doubles, pair, "undo-check-in")["checked_in_at"] is None


def test_doubles_are_two_players_and_teams_a_roster_with_a_captain(staff, cup, singles, doubles, teams):
    ama, kofi, esi, yaw = (player(name) for name in ("Ama", "Kofi", "Esi", "Yaw"))
    as_ama = logged_in(ama)

    def refused(event, field, **body):
        response = as_ama.post(entries_url(cup, event), body, format="json")
        assert response.status_code == 400 and field in response.json()["fields"], response.json()

    refused(doubles, "player_ids")  # alone
    refused(doubles, "player_ids", player_ids=[str(ama.id), str(ama.id)])  # twice the same player
    refused(doubles, "player_ids", player_ids=[str(ama.id), str(kofi.id), str(esi.id)])
    refused(doubles, "player_ids", player_ids=[str(kofi.id), str(esi.id)])  # not the caller's own
    refused(doubles, "player_ids", player_ids=[str(ama.id), "6a1f7d0e-0000-4000-8000-000000000000"])
    refused(singles, "player_ids", player_ids=[str(ama.id), str(kofi.id)])
    unverified = make_user("new@example.com")
    unverified.email_verified_at = None
    unverified.save()
    refused(doubles, "player_ids", player_ids=[str(ama.id), str(unverified.id)])

    mail.outbox.clear()
    pair = enter(as_ama, cup, doubles, player_ids=[str(ama.id), str(kofi.id)])
    assert names(pair) == ["Ama", "Kofi"] and pair["status"] == "pending"
    # The partner is told, since someone else put their name down.
    assert [m.to for m in mail.outbox] == [[kofi.email]] and "Ama entered you" in mail.outbox[0].body
    assert logged_in(kofi).get(ME).json()["results"][0]["mine"] is True

    roster = [str(u.id) for u in (ama, esi, yaw)]
    refused(teams, "team_name", player_ids=roster)
    refused(teams, "player_ids", player_ids=[str(ama.id)], team_name="Solo")
    refused(teams, "captain_id", player_ids=roster, team_name="Tudor", captain_id=str(kofi.id))
    team = enter(as_ama, cup, teams, player_ids=roster, team_name="  Tudor Smashers ")
    assert team["team_name"] == "Tudor Smashers" and team["captain_id"] == str(ama.id)
    assert names(team) == ["Ama", "Esi", "Yaw"]
    other = enter(
        logged_in(kofi),
        cup,
        teams,
        player_ids=[str(kofi.id), str(unverified.id)],
        expect=400,
    )
    assert "player_ids" in other["fields"]
    taken = as_ama.post(
        entries_url(cup, teams),
        {"player_ids": [str(kofi.id), str(ama.id)], "team_name": "tudor smashers"},
        format="json",
    )
    assert taken.status_code == 409


def test_a_player_is_in_one_standing_entry_per_event(staff, cup, singles, doubles):
    ama, kofi, esi = player("Ama"), player("Kofi"), player("Esi")
    as_ama = logged_in(ama)
    first = enter(as_ama, cup, doubles, player_ids=[str(ama.id), str(kofi.id)])

    # Kofi is taken, whoever asks and whichever status the first entry is in.
    for client, ids in ((logged_in(esi), [esi.id, kofi.id]), (staff, [kofi.id, esi.id])):
        response = client.post(
            entries_url(cup, doubles), {"player_ids": [str(i) for i in ids]}, format="json"
        )
        assert response.status_code == 409 and response.json()["code"] == "already_entered"
        # Staff are told who; another player isn't, because a pending entry is not theirs to see.
        assert ("Kofi" in response.json()["message"]) == (client is staff)
    mine = as_ama.post(entries_url(cup, doubles), {"player_ids": [str(ama.id), str(esi.id)]}, format="json")
    assert mine.json()["message"] == "You are already entered in this event."
    # The database refuses it too, should two requests ever pass the check together.
    other = Entry.objects.create(event_id=doubles["id"])
    with pytest.raises(IntegrityError, match="one_live_entry_per_event"), transaction.atomic():
        EntryPlayer.objects.create(entry=other, event_id=doubles["id"], user=kofi)
    other.delete()

    # Another event is another matter, and a withdrawn entry frees its players.
    enter(as_ama, cup, singles)
    act(logged_in(kofi), cup, doubles, first, "withdraw")
    again = enter(logged_in(esi), cup, doubles, player_ids=[str(esi.id), str(kofi.id)])
    assert names(again) == ["Esi", "Kofi"]
    assert Entry.objects.filter(event_id=doubles["id"]).count() == 2


@pytest.mark.django_db(transaction=True)
def test_twenty_simultaneous_acceptances_fill_exactly_the_last_place():
    """EVAL-008: one place left, twenty acceptance requests at once."""
    admin = make_user("admin@example.com", display_name="Club Admin")
    from .test_roles import create_club

    club = create_club(admin)
    staff = logged_in(admin)
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, capacity=3)
    cup = do(staff, tournament, "publish")
    event = cup["events"][0]

    def pending(i):
        entry = Entry.objects.create(event_id=event["id"])
        EntryPlayer.objects.create(entry=entry, event_id=event["id"], user=player(f"Player{i}"))
        return {"id": str(entry.id)}

    waiting = [pending(i) for i in range(22)]
    for entry in waiting[:2]:
        act(staff, cup, event, entry, "accept")
    clients = []
    for _ in range(20):
        cache.clear()  # twenty logins in a row would trip the login throttle
        clients.append(logged_in(admin))
    barrier = threading.Barrier(20)
    statuses = []

    def accept(client, entry):
        try:
            barrier.wait()
            response = client.post(entries_url(cup, event, entry, "accept"), {}, format="json")
            statuses.append((response.status_code, response.json().get("code")))
        finally:
            connection.close()

    threads = [threading.Thread(target=accept, args=pair) for pair in zip(clients, waiting[2:], strict=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    print("race:", sorted(statuses))
    assert Entry.objects.filter(event_id=event["id"], status="accepted").count() == 3
    assert sorted(statuses) == [(200, None)] + [(409, "event_full")] * 19
    assert Entry.objects.filter(event_id=event["id"], status="pending").count() == 19


def test_the_waiting_list_is_promoted_by_staff_and_capacity_is_checked_again(staff, cup, singles):
    ama, kofi, esi = player("Ama"), player("Kofi"), player("Esi")
    first, second, third = (enter(logged_in(u), cup, singles) for u in (ama, kofi, esi))
    act(staff, cup, singles, first, "accept")
    act(staff, cup, singles, second, "accept")

    full = act(staff, cup, singles, third, "accept", expect=409)
    assert full["code"] == "event_full"
    mail.outbox.clear()
    assert act(staff, cup, singles, third, "waitlist")["status"] == "waitlisted"
    assert [m.to for m in mail.outbox] == [[esi.email]] and "waiting list" in mail.outbox[0].subject

    # Still full: promotion is refused, and a withdrawal promotes nobody by itself.
    assert act(staff, cup, singles, third, "accept", expect=409)["code"] == "event_full"
    act(logged_in(ama), cup, singles, first, "withdraw")
    assert Entry.objects.get(pk=third["id"]).status == "waitlisted"

    mail.outbox.clear()
    assert act(staff, cup, singles, third, "accept")["status"] == "accepted"
    assert [m.to for m in mail.outbox] == [[esi.email]] and "place opened up" in mail.outbox[0].subject
    assert logged_in(esi).get(url(cup)).json()["events"][0]["accepted_count"] == 2

    # Entered by staff: a place if there is one, the waiting list if not.
    yaw, adwoa = player("Yaw"), player("Adwoa")
    mail.outbox.clear()
    assert enter(staff, cup, singles, player_ids=[str(yaw.id)])["status"] == "waitlisted"
    assert "waiting list" in mail.outbox[0].subject
    act(staff, cup, singles, second, "staff-withdraw", reason="Injured")
    assert enter(staff, cup, singles, player_ids=[str(adwoa.id)])["status"] == "accepted"
    assert "Club Admin entered you" in mail.outbox[-1].body

    # Capacity can't drop below what is already accepted.
    response = staff.patch(url(cup, event=singles), {"capacity": 1}, format="json")
    assert response.status_code == 400 and "capacity" in response.json()["fields"]
    response = staff.patch(url(cup, event=singles), {"kind": "doubles"}, format="json")
    assert response.status_code == 409 and response.json()["code"] == "has_entries"


def test_rejection_and_withdrawal_carry_their_reason_to_the_players_only(staff, cup, singles):
    ama, kofi = player("Ama"), player("Kofi")
    entry = enter(logged_in(ama), cup, singles)
    mail.outbox.clear()
    rejected = act(staff, cup, singles, entry, "reject", reason="Juniors only")
    assert rejected["status"] == "rejected" and rejected["reason"] == "Juniors only"
    assert "Juniors only" in mail.outbox[0].body
    assert [e["reason"] for e in listed(logged_in(ama), cup, singles)] == ["Juniors only"]
    assert listed(logged_in(kofi), cup, singles) == []
    assert [e["status"] for e in listed(staff, cup, singles, "?status=rejected")] == ["rejected"]
    assert listed(staff, cup, singles, "?status=accepted") == []
    assert staff.get(entries_url(cup, singles) + "?status=nope").status_code == 400

    # Decided is decided: a rejected entry is neither accepted nor withdrawn; the player enters again.
    for action in ("accept", "waitlist", "staff-withdraw"):
        assert act(staff, cup, singles, entry, action, expect=409)["code"] == "invalid_transition"
    assert act(logged_in(ama), cup, singles, entry, "withdraw", expect=409)["code"] == "invalid_transition"
    again = enter(logged_in(ama), cup, singles)
    act(staff, cup, singles, again, "accept")
    mail.outbox.clear()
    gone = act(staff, cup, singles, again, "staff-withdraw", reason="Asked by phone")
    assert gone["status"] == "withdrawn" and gone["withdrawn_at"] and gone["reason"] == "Asked by phone"
    assert "Club Admin withdrew" in mail.outbox[0].body and "Asked by phone" in mail.outbox[0].body


def test_check_in_is_its_own_thing(staff, cup, singles):
    ama = player("Ama")
    entry = enter(logged_in(ama), cup, singles)
    assert act(staff, cup, singles, entry, "check-in", expect=409)["code"] == "not_accepted"
    act(staff, cup, singles, entry, "accept")

    # The event has a fee and nothing was ever recorded about it: check-in doesn't ask.
    checked = act(staff, cup, singles, entry, "check-in")
    assert checked["checked_in_at"] and checked["status"] == "accepted"
    assert act(staff, cup, singles, entry, "check-in")["checked_in_at"] == checked["checked_in_at"]
    assert act(staff, cup, singles, entry, "undo-check-in")["checked_in_at"] is None

    # It still works once play has begun, and a withdrawal before that clears it.
    act(staff, cup, singles, entry, "check-in")
    withdrawn = act(logged_in(ama), cup, singles, entry, "withdraw")
    assert withdrawn["status"] == "withdrawn" and withdrawn["checked_in_at"] is None
    late = enter(staff, cup, singles, player_ids=[str(ama.id)])
    do(staff, cup, "start")
    do(staff, cup, "start", singles)
    assert act(staff, cup, singles, late, "check-in")["checked_in_at"]
    # Once the event has started entries are fixed: leaving it is a matter for the matches.
    for client, action in ((logged_in(ama), "withdraw"), (staff, "staff-withdraw"), (staff, "waitlist")):
        assert act(client, cup, singles, late, action, expect=409)["code"] == "entries_closed"
    assert enter(logged_in(player("Kofi")), cup, singles, expect=409)["code"] == "entries_closed"


def test_players_enter_inside_the_registration_window_and_staff_at_any_time(staff, cup, singles):
    ama = player("Ama")
    now = timezone.now()
    event = Event.objects.filter(pk=singles["id"])

    event.update(registration_opens_at=now + timedelta(hours=1))
    assert enter(logged_in(ama), cup, singles, expect=409)["code"] == "registration_not_open"
    event.update(
        registration_opens_at=now - timedelta(days=2), registration_closes_at=now - timedelta(hours=1)
    )
    assert enter(logged_in(ama), cup, singles, expect=409)["code"] == "registration_closed"
    assert enter(staff, cup, singles, player_ids=[str(ama.id)])["status"] == "accepted"

    event.update(registration_closes_at=now + timedelta(hours=1))
    assert enter(logged_in(player("Kofi")), cup, singles)["status"] == "pending"


def test_only_staff_decide_and_only_its_players_withdraw_an_entry(staff, club, cup, singles):
    ama, kofi = player("Ama"), player("Kofi")
    entry = enter(logged_in(ama), cup, singles)
    stranger = logged_in(kofi)
    for action in ("accept", "waitlist", "reject", "staff-withdraw", "check-in", "undo-check-in"):
        assert act(stranger, cup, singles, entry, action, expect=403)["code"] == "permission_denied"
    # Somebody else's pending entry isn't there at all.
    act(stranger, cup, singles, entry, "withdraw", expect=404)
    assert Entry.objects.get(pk=entry["id"]).status == "pending"
    # The entry is reached through its own event only.
    other_event = cup["events"][1]
    act(staff, cup, other_event, entry, "accept", expect=404)

    # A draft takes no entries, and for players it doesn't exist.
    draft = add_event(staff, make_tournament(staff, club, name="Next year"))
    assert enter(staff, draft, draft["events"][0], player_ids=[str(ama.id)], expect=409)["code"] == (
        "not_published"
    )
    assert logged_in(ama).post(entries_url(draft, draft["events"][0]), {}, format="json").status_code == 404
    assert logged_in(ama).get(entries_url(draft, draft["events"][0])).status_code == 404
    assert BrowserlessGet(entries_url(cup, singles)) == 401


def BrowserlessGet(path) -> int:
    from .conftest import BrowserClient

    return BrowserClient().get(path).status_code


def test_entries_page_through_a_stable_order(staff, cup, doubles):
    for i in range(5):
        a, b = player(f"A{i}"), player(f"B{i}")
        enter(staff, cup, doubles, player_ids=[str(a.id), str(b.id)])
    first = staff.get(entries_url(cup, doubles) + "?page_size=2").json()
    assert first["count"] == 5 and len(first["results"]) == 2 and first["next"]
    everyone = [names(e)[0] for e in listed(staff, cup, doubles)]
    assert everyone == [f"A{i}" for i in range(5)]
    assert ORGS  # entries are reached through the tournament, never through the organization


def test_a_mail_fault_after_the_change_is_saved_is_not_an_error(staff, cup, singles, monkeypatch):
    entry = enter(logged_in(player("Ama")), cup, singles)

    def broken(*args, **kwargs):
        raise OSError("smtp down")

    monkeypatch.setattr("competitions.emails.send_mail", broken)
    assert act(staff, cup, singles, entry, "accept")["status"] == "accepted"


def test_entering_is_rate_limited_per_caller(staff, cup, singles, settings):
    ama = logged_in(player("Ama"))
    for _ in range(30):
        ama.post(entries_url(cup, singles), {"player_ids": []}, format="json")
    assert ama.post(entries_url(cup, singles), {}, format="json").status_code == 429
    assert listed(ama, cup, singles) == []  # reading is not limited


def test_a_player_of_another_club_enters_a_public_event_without_joining_the_host(staff, cup, singles, club):
    """EVAL-004: entering club C's public event never makes the player a member of C, or asks to be."""
    from organizations.models import JoinRequest, Membership

    from .test_roles import create_club

    juma = player("Juma")
    home = create_club(juma, name="Kilifi Smashers")  # Juma runs his own club
    found = logged_in(juma).get("/api/v1/tournaments/").json()["results"]
    assert cup["id"] in [t["id"] for t in found], "the public list shows other clubs' tournaments"
    entry = enter(logged_in(juma), cup, singles)
    assert entry["status"] == "pending" and names(entry) == ["Juma"]
    act(staff, cup, singles, entry, "accept")
    assert not Membership.objects.filter(organization=club, user=juma).exists()
    assert not JoinRequest.objects.filter(organization=club, user=juma).exists()
    assert list(Membership.objects.filter(user=juma).values_list("organization_id", flat=True)) == [home.id]
    members = staff.get(f"{ORGS}{club.id}/members/").json()["results"]
    assert juma.email not in str(members)
