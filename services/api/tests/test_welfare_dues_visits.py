"""Welfare projects made a due, and planned visits linked through activities (REQ-038, REQ-039; TASK-075)."""

import uuid
from datetime import timedelta

import pytest

from finance.models import Campaign, Charge
from organizations.committee import local_today
from organizations.models import Role

from .helpers import logged_in, make_user
from .test_activities import create as create_activity
from .test_activities import rsvp
from .test_activities import url as activity_url
from .test_roles import ORGS, add_member
from .test_welfare import SECRET, give, path, seen

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(club):
    treasurer = Role.objects.create(organization=club, name="Finance", permissions=["finances.manage"])
    welfare = Role.objects.create(organization=club, name="Welfare", permissions=["welfare.manage"])
    social = Role.objects.create(organization=club, name="Social", permissions=["activities.manage"])
    found = {}
    for name in "ABCD":
        found[name] = make_user(f"{name.lower()}@example.com", display_name=f"Member {name}")
        add_member(club, found[name])
    for name, role in (("T", treasurer), ("W", welfare), ("S", social)):
        found[name] = make_user(f"{name.lower()}@example.com", display_name=role.name)
        add_member(club, found[name], role)
    return found


@pytest.fixture
def project(staff, club, people):
    made = staff.post(
        path(club),
        {
            "title": "Support A",
            "description": f"A is {SECRET}.",
            "beneficiary_id": str(people["A"].id),
            "suggested_minor": 5000,
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    return made.json()


def make_due(client, club, project, expect=200, **body):
    response = client.post(path(club, f"{project['id']}/due/"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def pay_due(client, club, member, amount):
    due = Charge.objects.get(kind=Charge.Kind.DUE, member=member)
    payment = client.post(
        f"{ORGS}{club.id}/finance/payments/",
        {
            "payer_id": str(member.id),
            "amount_minor": amount,
            "method": "mpesa",
            "received_on": "2026-11-20",
            "request_key": str(uuid.uuid4()),
        },
        format="json",
    ).json()
    allocated = client.post(
        f"{ORGS}{club.id}/finance/payments/{payment['id']}/allocate/",
        {"charge_id": str(due.id), "amount_minor": amount},
        format="json",
    )
    assert allocated.status_code == 200, allocated.json()


def test_voluntary_until_staff_holding_both_permissions_make_it_a_due(staff, club, people, project):
    assert project["required"] is False and project["due"] is None and project["my_due"] is None
    assert Charge.objects.filter(kind=Charge.Kind.DUE).count() == 0
    # It makes members owe, so it takes welfare.manage and finances.manage together.
    for name in "TWB":
        assert make_due(logged_in(people[name]), club, project, expect=403)["code"] == "permission_denied"
    today = local_today(club)
    shown = make_due(staff, club, project)
    assert shown["required"] is True
    assert shown["due"] == {"amount_minor": 5000, "due_on": today.isoformat()}
    # Every active member owes once, except the beneficiary.
    owing = set(Charge.objects.filter(kind=Charge.Kind.DUE).values_list("member_id", flat=True))
    assert people["A"].id not in owing
    assert {people[n].id for n in "BCDTWS"} <= owing
    assert make_due(staff, club, project, expect=409)["code"] == "already_due"
    # Nothing about the beneficiary or their circumstances reaches the member's dues list.
    mine = logged_in(people["B"]).get(f"{ORGS}{club.id}/my-finances/").content.decode()
    assert SECRET not in mine and "Support A" not in mine and "Welfare project due" in mine
    a = seen(logged_in(people["A"]), club, project).json()
    assert a["my_due"] is None


def test_dues_paid_count_towards_the_project_and_stay_out_of_general_totals(staff, club, people, project):
    make_due(staff, club, project, amount_minor=3000)
    treasurer = logged_in(people["T"])
    pay_due(treasurer, club, people["B"], 3000)
    pay_due(treasurer, club, people["C"], 1000)
    give(treasurer, club, project, people["D"], 2000)  # a gift on top still counts
    b = seen(logged_in(people["B"]), club, project).json()
    assert b["received_minor"] == 6000 and b["my_contribution_minor"] == 3000
    assert b["my_due"]["status"] == "paid" and b["expected_minor"] is None
    c = seen(logged_in(people["C"]), club, project).json()
    assert (c["my_due"]["outstanding_minor"], c["my_due"]["status"]) == (2000, "partial")
    owed = Charge.objects.filter(kind=Charge.Kind.DUE).count()
    assert seen(treasurer, club, project).json()["expected_minor"] == owed * 3000 - 4000
    summary = staff.get(f"{ORGS}{club.id}/finance/summary/").json()
    assert all(r["title"] != "Welfare project due" for r in summary)
    # Spending goes on the project, not on its campaign.
    campaign = Campaign.objects.get(welfare_project__isnull=False)
    spent = treasurer.post(
        f"{ORGS}{club.id}/finance/expenses/",
        {
            "description": "Gift",
            "amount_minor": 100,
            "spent_on": "2026-11-20",
            "campaign_id": str(campaign.id),
        },
        format="json",
    )
    assert spent.status_code == 400 and spent.json()["code"] == "bad_campaign"


def test_overdue_only_once_required_and_closing_stops_the_campaign(staff, club, people, project):
    make_due(staff, club, project)
    Charge.objects.filter(kind=Charge.Kind.DUE).update(due_on=local_today(club) - timedelta(days=2))
    assert seen(logged_in(people["C"]), club, project).json()["my_due"]["status"] == "overdue"
    staff.post(path(club, f"{project['id']}/close/"), format="json")
    assert Campaign.objects.get(welfare_project__isnull=False).closed_at is not None
    assert make_due(staff, club, project, expect=409)["code"] == "project_closed"


def test_due_terms_are_checked(staff, club, people):
    bare = staff.post(path(club), {"title": "Support B"}, format="json").json()
    assert make_due(staff, club, bare, expect=400)["code"] == "amount_required"
    yesterday = (local_today(club) - timedelta(days=1)).isoformat()
    assert (
        make_due(staff, club, bare, expect=400, amount_minor=100, due_on=yesterday)["code"] == "due_in_past"
    )
    picked = staff.post(
        path(club),
        {
            "title": "Support C",
            "audience": "selected",
            "member_ids": [str(people["B"].id), str(people["C"].id)],
        },
        format="json",
    ).json()
    make_due(staff, club, picked, amount_minor=100)
    owing = set(Charge.objects.filter(kind=Charge.Kind.DUE).values_list("member_id", flat=True))
    assert owing == {people["B"].id, people["C"].id}


def test_a_planned_visit_shows_on_the_project_with_who_is_going(staff, club, people, project):
    link = {"welfare_project_id": project["id"], "kind": "visit", "title": "Hospital visit"}
    # Linking takes welfare.manage as well as activities.manage.
    social = logged_in(people["S"])
    assert create_activity(social, club, expect=403, **link)["code"] == "permission_denied"
    assert create_activity(staff, club, expect=400, public=True, **link)["code"] == "welfare_not_public"
    visit = create_activity(
        staff, club, audience="selected", invitee_ids=[str(people[n].id) for n in "BC"], **link
    )
    assert visit["welfare_project_id"] == project["id"]
    assert seen(logged_in(people["B"]), club, project).json()["visits"] == []  # still a draft
    staff.post(activity_url(club, visit, "publish/"), {}, format="json")
    rsvp(logged_in(people["B"]), club, visit, "going")
    visits = seen(logged_in(people["B"]), club, project).json()["visits"]
    assert [(v["title"], v["going"]) for v in visits] == [("Hospital visit", ["Member B"])]
    # Someone in the project's audience but not invited to the visit doesn't see it.
    assert seen(logged_in(people["D"]), club, project).json()["visits"] == []
    # An activities officer can still edit the visit's time and place, not its link.
    assert (
        social.patch(activity_url(club, visit), {"place": "Coast General"}, format="json").status_code == 200
    )
    unlinked = social.patch(activity_url(club, visit), {"welfare_project_id": None}, format="json")
    assert unlinked.status_code == 403
    assert social.patch(activity_url(club, visit), {"public": True}, format="json").status_code == 400
    # Hidden with the project at the beneficiary's request.
    logged_in(people["A"]).post(path(club, f"{project['id']}/hide/"), format="json")
    b = logged_in(people["B"])
    assert b.get(activity_url(club, visit)).status_code == 404
    assert all(a["id"] != visit["id"] for a in b.get(activity_url(club)).json()["results"])
    assert rsvp(b, club, visit, "maybe", expect=404)


def test_a_visit_for_a_selected_project_invites_only_its_audience(staff, club, people):
    picked = staff.post(
        path(club),
        {
            "title": "Support D",
            "audience": "selected",
            "beneficiary_id": str(people["D"].id),
            "member_ids": [str(people["B"].id)],
        },
        format="json",
    ).json()
    link = {"welfare_project_id": picked["id"], "kind": "visit"}
    everyone = create_activity(staff, club, expect=400, **link)
    assert everyone["code"] == "outside_welfare_audience"
    outside = create_activity(
        staff, club, expect=400, audience="selected", invitee_ids=[str(people["C"].id)], **link
    )
    assert outside["code"] == "outside_welfare_audience"
    create_activity(
        staff, club, audience="selected", invitee_ids=[str(people["B"].id), str(people["D"].id)], **link
    )
    staff.post(path(club, f"{picked['id']}/close/"), format="json")
    late = create_activity(
        staff, club, expect=409, audience="selected", invitee_ids=[str(people["B"].id)], **link
    )
    assert late["code"] == "project_closed"
