"""Facility prices, door visits and takings (REQ-044, EVAL-044; TASK-102)."""

from datetime import timedelta

import pytest

from facilities.models import Visit
from organizations.models import Organization, Role

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db
MINE = "/api/v1/me/facility-visits/"


def branch_url(club, venue, tail=""):
    return f"{ORGS}{club.id}/venues/{venue['id']}/{tail}"


def price(staff, club, venue, expect=201, **body):
    response = staff.post(branch_url(club, venue, "passes/"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def visit(staff, club, venue, expect=201, **body):
    response = staff.post(branch_url(club, venue, "visits/"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


@pytest.fixture
def hall(club, staff):
    Organization.objects.filter(pk=club.pk).update(kind="facility")
    venue = make_venue(staff, club, name="Tononoka Hall")
    add_table(staff, club, venue, "Table 1")
    staff.patch(f"{ORGS}{club.id}/venues/{venue['id']}/", {"profile": "public"}, format="json")
    return venue


@pytest.fixture
def prices(staff, club, hall):
    day = price(staff, club, hall, name="Day pass", kind="day", amount_minor=20000, benefits=["Table time"])
    month = price(
        staff, club, hall, name="Month pass", kind="month", amount_minor=200000, benefits=["Ball hire"]
    )
    return {"day": day, "month": month}


@pytest.fixture
def faith():
    return make_user("faith@example.com", display_name="Faith")


def test_prices_are_minor_units_with_currency_and_show_on_the_profile(staff, club, hall, prices):
    assert (prices["day"]["amount_minor"], prices["day"]["currency"]) == (20000, "KES")
    assert price(staff, club, hall, expect=400, name="Bad", kind="day", amount_minor=-1)["fields"]
    bundle = price(staff, club, hall, expect=400, name="Ten visits", kind="sessions", amount_minor=150000)
    assert "sessions" in bundle["fields"]
    made = price(
        staff, club, hall, name="Ten visits", kind="sessions", amount_minor=150000, sessions=10, valid_days=60
    )
    assert (made["sessions"], made["valid_days"]) == (10, 60)
    # Switched off prices leave the profile; a price keeps its kind.
    staff.patch(branch_url(club, hall, f"passes/{made['id']}/"), {"active": False}, format="json")
    kind = staff.patch(
        branch_url(club, hall, f"passes/{prices['day']['id']}/"), {"kind": "week"}, format="json"
    )
    assert kind.status_code == 400
    player = logged_in(make_user("player@example.com"))
    shown = player.get(f"/api/v1/facilities/{hall['id']}/").json()["passes"]
    assert [(p["name"], p["amount_minor"], p["currency"]) for p in shown] == [
        ("Day pass", 20000, "KES"),
        ("Month pass", 200000, "KES"),
    ]


def test_the_door_records_a_walk_in_and_a_player_and_reverses_a_mistake(staff, club, hall, prices, faith):
    walk_in = visit(
        staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma at the door", method="cash"
    )
    assert (walk_in["amount_minor"], walk_in["method"], walk_in["walk_in_name"]) == (
        20000,
        "cash",
        "Juma at the door",
    )
    assert walk_in["valid_until"] == walk_in["visited_on"]
    # An M-Pesa payment needs its reference; the amount is the price, whatever is sent.
    refused = visit(
        staff, club, hall, expect=400, pass_id=prices["month"]["id"], player_id=str(faith.id), method="mpesa"
    )
    assert refused["code"] == "reference_required"
    month = visit(
        staff,
        club,
        hall,
        pass_id=prices["month"]["id"],
        player_id=str(faith.id),
        method="mpesa",
        reference="QK12AB34",
        amount_minor=1,
    )
    assert (month["amount_minor"], month["reference"], month["player_name"]) == (200000, "QK12AB34", "Faith")
    assert month["valid_until"] > month["visited_on"]
    # Nobody needs a name and a player at once; somebody is needed.
    assert visit(staff, club, hall, expect=400, pass_id=prices["day"]["id"], method="cash")["fields"]
    listed = staff.get(branch_url(club, hall, "visits/")).json()
    assert len(listed) == 2
    # Reversal keeps the original, with who and why.
    path = branch_url(club, hall, f"visits/{walk_in['id']}/reverse/")
    assert staff.post(path, {}, format="json").status_code == 400  # a reason is needed
    reversed_ = staff.post(path, {"reason": "Recorded twice"}, format="json").json()
    assert (reversed_["reversed"], reversed_["reversal_reason"], reversed_["amount_minor"]) == (
        True,
        "Recorded twice",
        20000,
    )
    assert staff.post(path, {"reason": "Again"}, format="json").json()["code"] == "already_reversed"
    assert Visit.objects.count() == 2


def backdate(visit_id, days):
    """Move a recorded visit (and the days its pass covers) into the past."""
    made = Visit.objects.get(pk=visit_id)
    Visit.objects.filter(pk=visit_id).update(
        visited_on=made.visited_on - timedelta(days=days), valid_until=made.valid_until - timedelta(days=days)
    )


def test_a_pass_covers_later_visits(staff, club, hall, prices, faith):
    month = visit(staff, club, hall, pass_id=prices["month"]["id"], player_id=str(faith.id), method="cash")
    # The day it was bought, the player is already in.
    assert (
        visit(staff, club, hall, expect=409, player_id=str(faith.id), method="pass")["code"]
        == "already_in_today"
    )
    # Bought yesterday: today's visit is on the pass and collects nothing.
    backdate(month["id"], 1)
    held = staff.get(branch_url(club, hall, "visits/active-pass/"), {"player": str(faith.id)}).json()
    assert held["id"] == month["id"]
    used = visit(staff, club, hall, player_id=str(faith.id), method="pass")
    assert (used["amount_minor"], used["method"], used["pass_name"]) == (0, "pass", "Month pass")
    assert (
        visit(staff, club, hall, expect=409, player_id=str(faith.id), method="pass")["code"]
        == "already_in_today"
    )
    # The sale can't be reversed while a visit on it stands.
    reverse = staff.post(
        branch_url(club, hall, f"visits/{month['id']}/reverse/"), {"reason": "x"}, format="json"
    )
    assert reverse.json()["code"] == "pass_in_use"
    # An expired pass covers nothing; nor does having no pass.
    backdate(month["id"], 40)
    assert staff.get(branch_url(club, hall, "visits/active-pass/"), {"player": str(faith.id)}).json() is None
    nobody = make_user("nobody@example.com")
    assert (
        visit(staff, club, hall, expect=409, player_id=str(nobody.id), method="pass")["code"]
        == "no_active_pass"
    )
    # A day pass covers only its own day.
    day = visit(staff, club, hall, pass_id=prices["day"]["id"], player_id=str(nobody.id), method="cash")
    backdate(day["id"], 1)
    assert (
        visit(staff, club, hall, expect=409, player_id=str(nobody.id), method="pass")["code"]
        == "no_active_pass"
    )


def test_a_bundle_covers_as_many_visits_as_it_has_sessions(staff, club, hall, faith):
    bundle = price(
        staff, club, hall, name="Three visits", kind="sessions", amount_minor=50000, sessions=3, valid_days=30
    )
    sale = visit(staff, club, hall, pass_id=bundle["id"], player_id=str(faith.id), method="cash")  # session 1
    backdate(sale["id"], 3)
    second = visit(staff, club, hall, player_id=str(faith.id), method="pass")
    backdate(second["id"], 1)
    visit(staff, club, hall, player_id=str(faith.id), method="pass")  # session 3
    assert (
        visit(staff, club, hall, expect=409, player_id=str(faith.id), method="pass")["code"]
        == "no_active_pass"
    )
    # Reversing a use gives the session back.
    staff.post(
        branch_url(club, hall, f"visits/{second['id']}/reverse/"), {"reason": "Wrong person"}, format="json"
    )
    assert (
        staff.get(branch_url(club, hall, "visits/active-pass/"), {"player": str(faith.id)}).json()["id"]
        == sale["id"]
    )


def test_takings_reconcile_and_need_the_finance_permission(staff, club, hall, prices, faith):
    other = make_venue(staff, club, name="Likoni Branch")
    other_day = price(staff, club, other, name="Day pass", kind="day", amount_minor=15000)
    visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma", method="cash")
    visit(
        staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Neema", method="mpesa", reference="QA1"
    )
    mistake = visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma", method="cash")
    visit(
        staff,
        club,
        hall,
        pass_id=prices["month"]["id"],
        player_id=str(faith.id),
        method="mpesa",
        reference="QB2",
    )
    visit(staff, club, other, pass_id=other_day["id"], walk_in_name="Baraka", method="cash")
    staff.post(branch_url(club, hall, f"visits/{mistake['id']}/reverse/"), {"reason": "Twice"}, format="json")
    takings = staff.get(f"{ORGS}{club.id}/facility-takings/").json()
    assert takings["total"] == [
        {"currency": "KES", "amount_minor": 20000 + 20000 + 200000 + 15000, "visits": 4}
    ]
    assert takings["reversed"] == 1
    assert {(r["venue_name"], r["amount_minor"]) for r in takings["by_branch"]} == {
        ("Tononoka Hall", 240000),
        ("Likoni Branch", 15000),
    }
    assert {(r["method"], r["amount_minor"]) for r in takings["by_method"]} == {
        ("cash", 35000),
        ("mpesa", 220000),
    }
    assert sum(r["amount_minor"] for r in takings["by_day"]) == takings["total"][0]["amount_minor"]
    assert sum(r["amount_minor"] for r in takings["by_pass"]) == takings["total"][0]["amount_minor"]
    one = staff.get(f"{ORGS}{club.id}/facility-takings/", {"venue": other["id"]}).json()
    assert one["total"][0]["amount_minor"] == 15000
    assert staff.get(f"{ORGS}{club.id}/facility-takings/", {"month": "2026-13"}).status_code == 400
    # Door staff without the finance permission record visits but can't see takings.
    door_role = Role.objects.create(organization=club, name="Door", permissions=["facilities.manage"])
    keeper = make_user("door@example.com")
    add_member(club, keeper, door_role)
    door = logged_in(keeper)
    visit(door, club, hall, pass_id=prices["day"]["id"], walk_in_name="Late", method="cash")
    assert door.get(f"{ORGS}{club.id}/facility-takings/").status_code == 403
    books_role = Role.objects.create(organization=club, name="Finance", permissions=["finances.view"])
    treasurer = make_user("books@example.com")
    add_member(club, treasurer, books_role)
    books = logged_in(treasurer)
    assert books.get(f"{ORGS}{club.id}/facility-takings/").status_code == 200
    assert books.get(branch_url(club, hall, "visits/")).status_code == 403


def test_a_player_sees_only_their_own_visits_and_never_walk_in_names(staff, club, hall, prices, faith):
    visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="MARK-WALK-IN", method="cash")
    visit(
        staff,
        club,
        hall,
        pass_id=prices["month"]["id"],
        player_id=str(faith.id),
        method="mpesa",
        reference="QC3",
    )
    mine = logged_in(faith).get(MINE)
    rows = mine.json()["results"]
    assert [(r["pass_name"], r["facility_name"], r["amount_minor"], r["reversed"]) for r in rows] == [
        ("Month pass", "Coast TT Club", 200000, False)
    ]
    assert "MARK-WALK-IN" not in mine.content.decode()
    assert "QC3" not in mine.content.decode()  # the reference stays with the facility
    stranger = logged_in(make_user("stranger@example.com"))
    assert stranger.get(MINE).json()["results"] == []
    assert stranger.get(branch_url(club, hall, "visits/")).status_code == 403
    assert (
        stranger.post(
            branch_url(club, hall, "passes/"), {"name": "x", "kind": "day", "amount_minor": 1}, format="json"
        ).status_code
        == 403
    )
