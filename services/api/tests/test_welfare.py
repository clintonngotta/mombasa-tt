"""Welfare projects (REQ-038, EVAL-038; TASK-074)."""

import uuid

import pytest

from finance.models import Charge
from notifications.models import Notification
from organizations.models import Role

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db
SECRET = "recovering from surgery"


def path(club, tail=""):
    return f"{ORGS}{club.id}/welfare-projects/{tail}"


@pytest.fixture
def people(club):
    treasurer_role = Role.objects.create(organization=club, name="Finance", permissions=["finances.manage"])
    found = {}
    for name in "ABCDE":
        found[name] = make_user(f"{name.lower()}@example.com", display_name=f"Member {name}")
        add_member(club, found[name])
    found["T"] = make_user("t@example.com", display_name="Treasurer")
    add_member(club, found["T"], treasurer_role)
    return found


@pytest.fixture
def project(staff, club, people):
    made = staff.post(
        path(club),
        {
            "title": "Support A",
            "description": f"A is {SECRET}; the family agreed to share this.",
            "beneficiary_id": str(people["A"].id),
            "suggested_minor": 5000,
            "target_minor": 20000,
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    return made.json()


def give(client, club, project, who, amount, expect=201, **body):
    response = client.post(
        path(club, f"{project['id']}/contributions/"),
        {
            "contributor_id": str(who.id),
            "amount_minor": amount,
            "method": "cash",
            "received_on": "2026-11-19",
            "request_key": str(uuid.uuid4()),
            **body,
        },
        format="json",
    )
    assert response.status_code == expect, response.json()
    return response.json()


def seen(client, club, project):
    return client.get(path(club, f"{project['id']}/"))


def test_totals_reconcile_through_a_reversal_and_a_deficit_and_nobody_owes(staff, club, people, project):
    treasurer = logged_in(people["T"])
    give(treasurer, club, project, people["B"], 5000)
    give(treasurer, club, project, people["C"], 2000)  # less than suggested: still just a gift
    give(treasurer, club, project, people["D"], 5000, anonymous=True)
    mistake = give(treasurer, club, project, people["C"], 3000)
    treasurer.post(
        path(club, f"{project['id']}/contributions/{mistake['id']}/reverse/"),
        {"reason": "Recorded under the wrong member"},
        format="json",
    )
    shown = seen(treasurer, club, project).json()
    assert (shown["received_minor"], shown["spent_minor"], shown["remaining_minor"]) == (12000, 0, 12000)
    treasurer.post(
        path(club, f"{project['id']}/expenses/"),
        {"description": "Visit gift", "amount_minor": 15000, "spent_on": "2026-11-20"},
        format="json",
    )
    shown = seen(treasurer, club, project).json()
    assert (shown["received_minor"], shown["spent_minor"], shown["remaining_minor"]) == (12000, 15000, -3000)
    # Giving creates nothing owed: no member has an outstanding or overdue welfare charge.
    statuses = {c["status"] for c in staff.get(f"{ORGS}{club.id}/finance/charges/").json()}
    assert statuses <= {"paid", "waived"}
    assert all(c.kind == "welfare" for c in Charge.objects.all())
    e_finances = logged_in(people["E"]).get(f"{ORGS}{club.id}/my-finances/").json()
    assert e_finances["charges"] == [] and e_finances["dues"] == []
    # Welfare money stays out of the general purpose totals.
    assert all(r["campaign_id"] is not None for r in staff.get(f"{ORGS}{club.id}/finance/summary/").json())


def test_members_see_totals_and_their_own_gift_and_anonymity_holds(staff, club, people, project):
    treasurer = logged_in(people["T"])
    give(treasurer, club, project, people["B"], 5000)
    give(treasurer, club, project, people["D"], 5000, anonymous=True)
    b = seen(logged_in(people["B"]), club, project).json()
    assert (b["received_minor"], b["target_minor"], b["my_contribution_minor"]) == (10000, 20000, 5000)
    assert b["contributors"] is None  # the club doesn't show a list
    e = seen(logged_in(people["E"]), club, project).json()
    assert e["my_contribution_minor"] == 0 and "status" not in e
    assert logged_in(people["B"]).get(path(club, f"{project['id']}/contributions/")).status_code == 403
    staff.patch(path(club, f"{project['id']}/"), {"show_contributors": True}, format="json")
    listed = seen(logged_in(people["E"]), club, project).json()["contributors"]
    assert sorted(c["name"] for c in listed) == ["Anonymous", "Member B"]
    assert "Member D" not in seen(logged_in(people["E"]), club, project).content.decode()
    # Staff still see who gave.
    names = {
        c["contributor_name"] for c in treasurer.get(path(club, f"{project['id']}/contributions/")).json()
    }
    assert names == {"Member B", "Member D"}


def test_the_beneficiary_can_hide_it_and_nothing_sensitive_leaves_the_club(staff, club, people, project):
    alerts = Notification.objects.filter(subject=f"welfare:{project['id']}")
    assert alerts.count() == 6  # members B to E, the treasurer and the admin; not A
    assert not alerts.filter(recipient=people["A"]).exists()
    for alert in alerts:
        assert SECRET not in alert.title + alert.body and "Support A" not in alert.title
    outsider = logged_in(make_user("x@example.com"))
    assert seen(outsider, club, project).status_code in (403, 404)
    assert outsider.get(path(club)).status_code in (403, 404)
    a = logged_in(people["A"])
    assert seen(a, club, project).status_code == 200
    assert logged_in(people["B"]).post(path(club, f"{project['id']}/hide/"), format="json").status_code == 403
    assert a.post(path(club, f"{project['id']}/hide/"), format="json").status_code == 204
    for name in "ABE":
        member = logged_in(people[name])
        assert seen(member, club, project).status_code == 404
        assert member.get(path(club)).json() == []
    assert seen(logged_in(people["T"]), club, project).json()["hidden"] is True


def test_a_closed_project_is_read_only(staff, club, people, project):
    treasurer = logged_in(people["T"])
    give(treasurer, club, project, people["B"], 5000)
    assert (
        logged_in(people["B"]).post(path(club, f"{project['id']}/close/"), format="json").status_code == 403
    )
    closed = staff.post(path(club, f"{project['id']}/close/"), format="json").json()
    assert closed["closed"] is True and closed["received_minor"] == 5000
    assert give(treasurer, club, project, people["C"], 5000, expect=409)["code"] == "project_closed"
    spent = treasurer.post(
        path(club, f"{project['id']}/expenses/"),
        {"description": "Gift", "amount_minor": 100, "spent_on": "2026-11-20"},
        format="json",
    )
    assert spent.status_code == 409
    assert staff.patch(path(club, f"{project['id']}/"), {"title": "x"}, format="json").status_code == 409


def test_selected_audience_only_and_setup_needs_the_welfare_permission(staff, club, people):
    made = staff.post(
        path(club),
        {"title": "Support C", "audience": "selected", "member_ids": [str(people["B"].id)]},
        format="json",
    ).json()
    assert seen(logged_in(people["B"]), club, made).status_code == 200
    assert seen(logged_in(people["E"]), club, made).status_code == 404
    assert logged_in(people["T"]).post(path(club), {"title": "x"}, format="json").status_code == 403
    # Same request twice records one gift.
    key = str(uuid.uuid4())
    treasurer = logged_in(people["T"])
    give(treasurer, club, made, people["B"], 5000, request_key=key)
    give(treasurer, club, made, people["B"], 5000, expect=200, request_key=key)
    assert seen(treasurer, club, made).json()["received_minor"] == 5000
