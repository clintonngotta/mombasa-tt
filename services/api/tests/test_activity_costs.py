"""Sharing an activity's cost through a one-time campaign and expenses (REQ-039 Phase 2; TASK-075)."""

import uuid
from datetime import timedelta

import pytest

from finance.models import Charge
from organizations.committee import local_today
from organizations.models import Role

from .helpers import logged_in, make_user
from .test_activities import create, rsvp, url
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(club):
    social = Role.objects.create(organization=club, name="Social", permissions=["activities.manage"])
    treasurer = Role.objects.create(organization=club, name="Finance", permissions=["finances.manage"])
    found = {}
    for name in "ABCD":
        found[name] = make_user(f"{name.lower()}@example.com", display_name=f"Member {name}")
        add_member(club, found[name])
    found["S"] = make_user("s@example.com", display_name="Social")
    add_member(club, found["S"], social)
    found["T"] = make_user("t@example.com", display_name="Treasurer")
    add_member(club, found["T"], treasurer)
    return found


@pytest.fixture
def clients(people):
    """One signed-in client each: signing in again and again trips the login rate limit."""
    return {name: logged_in(user) for name, user in people.items()}


@pytest.fixture
def night(staff, club, clients):
    made = create(staff, club, capacity=2, cost_note="About KES 500 each")
    staff.post(url(club, made, "publish/"), {}, format="json")
    rsvp(clients["A"], club, made, "going")
    rsvp(clients["B"], club, made, "going")
    rsvp(clients["C"], club, made, "going")  # waitlisted: no place, so no share
    rsvp(clients["D"], club, made, "maybe")
    return made


def share(client, club, activity, expect=200, **body):
    body.setdefault("due_on", local_today(club).isoformat())
    response = client.post(url(club, activity, "cost-share/"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_a_cost_note_alone_bills_nobody(staff, club, clients, night):
    shown = clients["A"].get(url(club, night)).json()
    assert shown["cost_share"] is None and shown["cost_note"] == "About KES 500 each"
    assert Charge.objects.count() == 0


def test_only_those_with_a_place_owe_and_it_takes_both_permissions(staff, club, people, clients, night):
    for name in "STA":
        assert share(clients[name], club, night, expect=403, amount_minor=50000)
    shown = share(staff, club, night, amount_minor=50000)
    assert shown["cost_share"]["amount_minor"] == 50000
    owing = set(Charge.objects.filter(kind=Charge.Kind.DUE).values_list("member_id", flat=True))
    assert owing == {people["A"].id, people["B"].id}
    assert share(staff, club, night, expect=409, amount_minor=1)["code"] == "already_shared"
    a = clients["A"].get(url(club, night)).json()["cost_share"]
    assert a["my_share"] == {"outstanding_minor": 50000, "status": "pending"}
    assert a["received_minor"] is None  # totals are for finance staff
    assert clients["C"].get(url(club, night)).json()["cost_share"]["my_share"] is None


def test_a_total_splits_evenly_rounded_up_and_reconciles_with_spending(staff, club, people, clients, night):
    share(staff, club, night, total_minor=100100)  # KES 1001 between two: KES 501 each
    assert set(Charge.objects.values_list("amount_minor", flat=True)) == {50100}
    treasurer = clients["T"]
    due = Charge.objects.get(member=people["A"])
    payment = treasurer.post(
        f"{ORGS}{club.id}/finance/payments/",
        {
            "payer_id": str(people["A"].id),
            "amount_minor": 50100,
            "method": "cash",
            "received_on": "2026-11-20",
            "request_key": str(uuid.uuid4()),
        },
        format="json",
    ).json()
    treasurer.post(
        f"{ORGS}{club.id}/finance/payments/{payment['id']}/allocate/",
        {"charge_id": str(due.id), "amount_minor": 50100},
        format="json",
    )
    treasurer.post(
        f"{ORGS}{club.id}/finance/expenses/",
        {
            "description": "Restaurant deposit",
            "amount_minor": 80000,
            "spent_on": "2026-11-20",
            "campaign_id": str(due.campaign_id),
        },
        format="json",
    )
    totals = treasurer.get(url(club, night)).json()["cost_share"]
    assert (totals["received_minor"], totals["spent_minor"], totals["remaining_minor"]) == (
        50100,
        80000,
        -29900,
    )
    assert clients["A"].get(url(club, night)).json()["cost_share"]["my_share"]["status"] == "paid"
    summary = {r["title"]: r for r in staff.get(f"{ORGS}{club.id}/finance/summary/").json()}
    assert summary["Night out"]["remaining_minor"] == -29900


def test_terms_are_checked(staff, club, people, night):
    assert share(staff, club, night, expect=400)["code"] == "amount_or_total"
    both = share(staff, club, night, expect=400, amount_minor=1, total_minor=1)
    assert both["code"] == "amount_or_total"
    yesterday = (local_today(club) - timedelta(days=1)).isoformat()
    assert share(staff, club, night, expect=400, amount_minor=1, due_on=yesterday)["code"] == "due_in_past"
    draft = create(staff, club)
    assert share(staff, club, draft, expect=409, amount_minor=1)["code"] == "activity_closed"
    empty = create(staff, club)
    staff.post(url(club, empty, "publish/"), {}, format="json")
    assert share(staff, club, empty, expect=409, amount_minor=1)["code"] == "nobody_going"


def test_a_welfare_visit_share_has_a_neutral_title(staff, club, people, clients):
    project = staff.post(
        f"{ORGS}{club.id}/welfare-projects/", {"title": "Support D after surgery"}, format="json"
    ).json()
    visit = create(staff, club, kind="visit", title="Visit D at home", welfare_project_id=project["id"])
    staff.post(url(club, visit, "publish/"), {}, format="json")
    rsvp(clients["A"], club, visit, "going")
    share(staff, club, visit, amount_minor=20000)
    assert Charge.objects.get(member=people["A"]).purpose == "Welfare visit share"
