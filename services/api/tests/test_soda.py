"""Soda games: friendly challenges with optional pledges (REQ-040, EVAL-040; TASK-076)."""

from datetime import UTC, datetime

import pytest

from competitions.models import Match, OfficialResult
from facilities.models import Visit
from ratings.models import Rating, RatingEvent
from reservations.models import Reservation
from soda.models import Challenge, Policy

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db
GAMES = "/api/v1/me/soda-games/"


@pytest.fixture
def people(club, admin):
    made = {"D": admin}
    for name in "ABC":
        user = make_user(f"{name.lower()}@example.com", display_name=f"Player {name}")
        add_member(club, user)
        made[name] = user
    return made


@pytest.fixture
def gate(settings):
    settings.SODA_STAKES_ENABLED = True
    return settings


def challenge(client, other, expect=201, **body):
    response = client.post(GAMES, {"challenged_id": str(other.id), "best_of": 3, **body}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def act(client, made, verb, expect=200, **body):
    response = client.post(f"{GAMES}{made['id']}/{verb}/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def untouched():
    return [m.objects.count() for m in (Rating, RatingEvent, Reservation, OfficialResult, Match, Visit)]


def test_with_the_gate_off_stakes_are_hidden_and_refused(people):
    a, b = logged_in(people["A"]), people["B"]
    assert a.get("/api/v1/me/soda-settings/").json() == {"stakes_available": False, "games_enabled": True}
    assert challenge(a, b, expect=409, stake_minor=10000)["code"] == "stakes_disabled"
    made = challenge(a, b, message="Loser buys sodas?", play_at=None)
    assert "stake_minor" not in made and "owed_by_id" not in made["outcome"]
    assert made["status"] == "pending" and made["play_at"] is None  # next time we meet


def test_only_the_loser_who_pledged_owes(people, gate):
    before = untouched()
    a, b = logged_in(people["A"]), logged_in(people["B"])
    # A pledges KES 100; B plays without staking; A loses: A owes.
    made = challenge(a, people["B"], stake_minor=10000)
    assert (made["stake_minor"], made["stake_currency"]) == (10000, "KES")
    act(b, made, "accept", match_stake=False)
    played = act(b, made, "result", games=[[5, 11], [9, 11]])
    assert played["outcome"] == {"state": "awaiting_confirmation", "winner_id": None, "owed_by_id": None}
    done = act(a, made, "confirm")
    assert done["outcome"] == {
        "state": "confirmed",
        "winner_id": str(people["B"].id),
        "owed_by_id": str(people["A"].id),
    }
    # The winner marks it settled; nothing else happens to money.
    assert act(a, made, "settle", expect=403)["code"] == "not_yours"
    assert act(b, made, "settle")["outcome"]["state"] == "settled"
    # Same stake, B matched it, B loses: B owes.
    second = challenge(a, people["B"], stake_minor=10000)
    act(b, second, "accept", match_stake=True)
    act(a, second, "result", games=[[11, 7], [11, 8]])
    assert act(b, second, "confirm")["outcome"]["owed_by_id"] == str(people["B"].id)
    # Only A staked and B loses: nobody owes.
    third = challenge(a, people["B"], stake_note="a soda")
    act(b, third, "accept")
    act(a, third, "result", games=[[11, 2], [11, 3]])
    shown = act(b, third, "confirm")["outcome"]
    assert (shown["winner_id"], shown["owed_by_id"]) == (str(people["A"].id), None)
    assert act(a, third, "settle", expect=409)["code"] == "nothing_owed"
    # Unrated, no table, no money.
    assert untouched() == before


def test_a_disputed_result_owes_nothing_until_recorded_again(people, gate):
    a, b = logged_in(people["A"]), logged_in(people["B"])
    made = challenge(a, people["B"], stake_minor=5000)
    act(b, made, "accept", match_stake=True)
    act(a, made, "result", games=[[11, 9], [11, 9]])
    disputed = act(b, made, "dispute", reason="It was 2-1 to me")
    assert disputed["outcome"] == {"state": "disputed", "winner_id": None, "owed_by_id": None}
    assert act(a, made, "confirm", expect=409)["code"] == "result_disputed"
    act(b, made, "result", games=[[11, 9], [8, 11], [9, 11]])
    final = act(a, made, "confirm")
    assert final["outcome"]["owed_by_id"] == str(people["A"].id)
    assert act(b, made, "result", expect=409, games=[[11, 0], [11, 0]])["code"] == "result_confirmed"
    assert act(a, made, "result", expect=400, games=[[11, 10], [11, 9]])["code"] == "bad_result"


def test_nobody_else_stakes_or_sees_a_stake(people, gate, club):
    a, b, c, d = (logged_in(people[k]) for k in "ABCD")
    made = challenge(a, people["B"], stake_minor=10000)
    for outsider in (c, d):
        assert outsider.get(f"{GAMES}{made['id']}/").status_code == 404
        assert act(outsider, made, "accept", expect=404, match_stake=True)
        assert outsider.get(GAMES).json()["results"] == []
    # Club members see a challenge only when both players share it, and never the stake.
    act(b, made, "accept")
    act(a, made, "share", share=True)
    assert c.get(f"{ORGS}{club.id}/soda-games/").json() == []
    act(b, made, "share", share=True)
    shared = c.get(f"{ORGS}{club.id}/soda-games/")
    assert [x["id"] for x in shared.json()] == [made["id"]]
    assert "stake" not in shared.content.decode()
    assert logged_in(make_user("x@example.com")).get(f"{ORGS}{club.id}/soda-games/").status_code == 403


def test_answers_belong_to_the_right_player(people, gate):
    a, b = logged_in(people["A"]), logged_in(people["B"])
    made = challenge(a, people["B"])
    assert act(a, made, "accept", expect=403)["code"] == "not_yours"
    assert act(b, made, "withdraw", expect=403)["code"] == "not_yours"
    countered = act(b, made, "counter", play_at="2026-12-01T17:00:00Z")
    assert countered["status"] == "countered"
    assert datetime.fromisoformat(countered["proposed_at"]) == datetime(2026, 12, 1, 17, tzinfo=UTC)
    accepted = act(a, made, "accept")
    assert accepted["status"] == "accepted"
    assert datetime.fromisoformat(accepted["play_at"]) == datetime(2026, 12, 1, 17, tzinfo=UTC)
    assert act(a, made, "withdraw", expect=409)["code"] == "challenge_closed"
    other = challenge(a, people["B"])
    assert act(a, other, "withdraw")["status"] == "withdrawn"
    third = challenge(a, people["B"])
    assert act(b, third, "decline")["status"] == "declined"
    assert act(a, third, "result", expect=409, games=[[11, 1], [11, 1]])["code"] == "challenge_closed"


def test_reach_and_the_clubs_switches(people, gate, club, staff):
    a = logged_in(people["A"])
    stranger = make_user("stranger@example.com")
    assert challenge(a, stranger, expect=400)["code"] == "not_reachable"
    assert challenge(a, people["A"], expect=400)["code"] == "not_reachable"
    # A player listed in the directory can be challenged without sharing a club.
    from profiles.models import PlayerProfile

    PlayerProfile.objects.update_or_create(user=stranger, defaults={"directory_opt_in": True})
    challenge(a, stranger)
    # The club switches stakes off, then soda games altogether, for its members.
    assert (
        logged_in(people["B"])
        .put(f"{ORGS}{club.id}/soda-policy/", {"games_enabled": True, "stakes_enabled": False}, format="json")
        .status_code
        == 403
    )
    policy = staff.put(
        f"{ORGS}{club.id}/soda-policy/", {"games_enabled": True, "stakes_enabled": False}, format="json"
    ).json()
    assert policy == {"games_enabled": True, "stakes_enabled": False, "stakes_available": True}
    assert challenge(a, people["B"], expect=409, stake_minor=100)["code"] == "stakes_disabled"
    assert "stake_minor" not in challenge(a, people["B"])
    staff.put(
        f"{ORGS}{club.id}/soda-policy/", {"games_enabled": False, "stakes_enabled": False}, format="json"
    )
    assert challenge(a, people["B"], expect=409)["code"] == "soda_disabled"
    assert Policy.objects.get(organization=club).games_enabled is False
    assert Challenge.objects.filter(stake_minor__isnull=False).count() == 0
