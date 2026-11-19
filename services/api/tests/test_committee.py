"""Committees: positions, holders, custom fields, granted roles and history (REQ-045, EVAL-045, TASK-106)."""

import pytest

from organizations.models import PositionHolder, Role
from organizations.permissions import Permission

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, create_club, my_permissions

pytestmark = pytest.mark.django_db


def url(club, path=""):
    return f"{ORGS}{club.id}/committee/{path}"


def position_named(committee, name):
    return next(p for p in committee["positions"] if p["name"] == name)


@pytest.fixture
def finance_role(club):
    return Role.objects.create(
        organization=club, name="Finance", permissions=[Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE]
    )


def test_admin_sets_up_the_committee_and_members_see_it(admin, club, staff, finance_role):
    treasurer = make_user("treasurer@example.com", display_name="Tabitha Treasurer")
    their = add_member(club, treasurer)
    member = make_user("member@example.com", display_name="Plain Member")
    add_member(club, member)

    chair = staff.post(url(club, "positions/"), {"name": "Chair"}, format="json")
    assert chair.status_code == 201
    created = staff.post(
        url(club, "positions/"),
        {
            "name": "Treasurer",
            "term_start": "2026-01-01",
            "term_end": "2027-12-31",
            "grants_role": str(finance_role.id),
        },
        format="json",
    ).json()
    assert [p["name"] for p in created["positions"]] == ["Chair", "Treasurer"]
    seat = position_named(created, "Treasurer")
    assert seat["grants_role"]["name"] == "Finance" and seat["term_end"] == "2027-12-31"

    # Names are unique among active positions; a term can't end before it starts.
    assert staff.post(url(club, "positions/"), {"name": "chair"}, format="json").status_code == 400
    bad = staff.patch(url(club, f"positions/{seat['id']}/"), {"term_end": "2025-01-01"}, format="json")
    assert bad.status_code == 400 and "term_end" in bad.json()["fields"]

    # A position field and a holder field, one visible to members and one for governance staff.
    portfolio = staff.post(
        url(club, "fields/"),
        {"label": "Portfolio", "kind": "text", "visibility": "member", "applies_to": "position"},
        format="json",
    ).json()
    elected = staff.post(
        url(club, "fields/"),
        {"label": "Elected at", "kind": "choice", "options": ["AGM", "SGM"], "applies_to": "holder"},
        format="json",
    ).json()
    assert elected["visibility"] == "staff"

    # A holder field needs a holder; holders come from the active members.
    values = url(club, f"positions/{seat['id']}/values/")
    early = staff.patch(values, {"values": {elected["id"]: "AGM"}}, format="json")
    assert early.status_code == 400
    outsider = add_member(create_club(make_user("other@example.com"), "Other"), make_user("o@example.com"))
    holder = url(club, f"positions/{seat['id']}/holder/")
    assert staff.put(holder, {"membership_id": str(outsider.id)}, format="json").status_code == 400
    assigned = staff.put(holder, {"membership_id": str(their.id), "started_on": "2026-02-01"}, format="json")
    assert assigned.status_code == 200
    assert position_named(assigned.json(), "Treasurer")["holder"]["display_name"] == "Tabitha Treasurer"

    saved = staff.patch(
        values, {"values": {portfolio["id"]: "Money matters", elected["id"]: "AGM"}}, format="json"
    ).json()
    seat = position_named(saved, "Treasurer")
    assert [(e["field"]["label"], e["value"]) for e in seat["values"]] == [("Portfolio", "Money matters")]
    assert [(e["field"]["label"], e["value"]) for e in seat["holder"]["values"]] == [("Elected at", "AGM")]
    assert staff.patch(values, {"values": {elected["id"]: "Raffle"}}, format="json").status_code == 400

    # Reorder: every active position, once.
    ids = [p["id"] for p in saved["positions"]]
    assert (
        staff.post(url(club, "positions/reorder/"), {"positions": ids[:1]}, format="json").status_code == 400
    )
    reordered = staff.post(url(club, "positions/reorder/"), {"positions": ids[::-1]}, format="json").json()
    assert [p["name"] for p in reordered["positions"]] == ["Treasurer", "Chair"]

    # Members see the committee by display name, without the granted role or staff-only fields.
    seen = logged_in(member).get(url(club)).json()
    assert seen["can_manage"] is False
    seat = position_named(seen, "Treasurer")
    assert seat["grants_role"] is None and seat["holder"]["display_name"] == "Tabitha Treasurer"
    assert [e["field"]["label"] for e in seat["values"]] == ["Portfolio"]
    assert seat["holder"]["values"] == []
    assert set(seat["holder"]) == {"id", "membership_id", "display_name", "started_on", "values"}
    assert logged_in(make_user("x@example.com")).get(url(club)).status_code == 403


def test_a_position_grants_its_role_only_while_held(admin, club, staff, finance_role):
    treasurer = make_user("treasurer@example.com")
    their = add_member(club, treasurer)
    seat = staff.post(
        url(club, "positions/"), {"name": "Treasurer", "grants_role": str(finance_role.id)}, format="json"
    ).json()["positions"][0]
    client = logged_in(treasurer)
    assert Permission.FINANCES_MANAGE not in my_permissions(client, club)

    staff.put(url(club, f"positions/{seat['id']}/holder/"), {"membership_id": str(their.id)}, format="json")
    assert sorted(my_permissions(client, club)) == [Permission.FINANCES_MANAGE, Permission.FINANCES_VIEW]
    # The finance permission and nothing more: no committee edits, no roles.
    assert client.post(url(club, "positions/"), {"name": "Vice chair"}, format="json").status_code == 403
    assert client.get(f"{ORGS}{club.id}/roles/").status_code == 403

    # Stepping down ends the grant; the time in office stays in the history.
    ended = staff.delete(url(club, f"positions/{seat['id']}/holder/"))
    assert position_named(ended.json(), "Treasurer")["holder"] is None
    assert my_permissions(client, club) == []
    history = client.get(url(club, "history/")).json()["results"]
    assert [(h["position"], h["end_reason"]) for h in history] == [("Treasurer", "stepped_down")]


def test_delegated_governance_and_its_limits(admin, club, staff, finance_role):
    secretary = make_user("secretary@example.com", display_name="Sec")
    delegate = Role.objects.create(
        organization=club, name="Governance", permissions=[Permission.GOVERNANCE_MANAGE]
    )
    add_member(club, secretary, delegate)
    committee_member = make_user("committee@example.com")
    theirs = add_member(club, committee_member, "committee")  # finances, welfare... but not governance
    client = logged_in(secretary)

    # A committee member without governance.manage can't change the committee or list candidates.
    other = logged_in(committee_member)
    assert other.post(url(club, "positions/"), {"name": "Chair"}, format="json").status_code == 403
    assert other.get(url(club, "candidates/")).status_code == 403
    assert other.get(url(club, "fields/")).status_code == 403

    # The delegate runs the committee and finds members to seat.
    made = client.post(url(club, "positions/"), {"name": "Chair"}, format="json")
    assert made.status_code == 201 and made.json()["can_manage"] is True
    chair = made.json()["positions"][0]
    names = [c["display_name"] for c in client.get(url(club, "candidates/?search=sec")).json()["results"]]
    assert names == ["Sec"]
    seated = client.put(
        url(club, f"positions/{chair['id']}/holder/"), {"membership_id": str(theirs.id)}, format="json"
    )
    assert seated.status_code == 200

    # ...but can't attach, hand out or take away a role beyond their own permissions.
    refused = client.post(
        url(club, "positions/"), {"name": "Treasurer", "grants_role": str(finance_role.id)}, format="json"
    )
    assert refused.status_code == 403 and refused.json()["code"] == "beyond_your_authority"
    treasurer = staff.post(
        url(club, "positions/"), {"name": "Treasurer", "grants_role": str(finance_role.id)}, format="json"
    ).json()
    seat = position_named(treasurer, "Treasurer")["id"]
    for call in (
        lambda: client.put(
            url(club, f"positions/{seat}/holder/"), {"membership_id": str(theirs.id)}, format="json"
        ),
        lambda: client.patch(url(club, f"positions/{seat}/"), {"grants_role": None}, format="json"),
        lambda: client.patch(
            url(club, f"positions/{chair['id']}/"), {"grants_role": str(finance_role.id)}, format="json"
        ),
    ):
        assert call().status_code == 403
    assert PositionHolder.objects.filter(position_id=seat).count() == 0

    # Admin and Member are never granted by a position, not even by the admin.
    for key in ("admin", "member"):
        role = club.roles.get(key=key)
        answer = staff.patch(
            url(club, f"positions/{chair['id']}/"), {"grants_role": str(role.id)}, format="json"
        )
        assert answer.status_code == 400


def test_replacing_leaving_and_retiring_keep_the_history(admin, club, staff):
    first = make_user("first@example.com", display_name="First Chair")
    second = make_user("second@example.com", display_name="Second Chair")
    first_m, second_m = add_member(club, first), add_member(club, second)
    chair = staff.post(url(club, "positions/"), {"name": "Chair"}, format="json").json()["positions"][0]
    holder = url(club, f"positions/{chair['id']}/holder/")

    staff.put(holder, {"membership_id": str(first_m.id)}, format="json")
    assert staff.put(holder, {"membership_id": str(first_m.id)}, format="json").status_code == 409
    staff.put(holder, {"membership_id": str(second_m.id)}, format="json")
    # The second chair leaves the club: the seat falls vacant.
    assert logged_in(second).post(f"/api/v1/me/memberships/{second_m.id}/leave/").status_code == 204
    assert staff.get(url(club)).json()["positions"][0]["holder"] is None

    staff.put(holder, {"membership_id": str(first_m.id)}, format="json")
    retired = staff.post(url(club, f"positions/{chair['id']}/retire/")).json()
    assert retired["positions"] == []
    # The retired position's name is free again.
    assert staff.post(url(club, "positions/"), {"name": "Chair"}, format="json").status_code == 201

    history = logged_in(first).get(url(club, "history/")).json()["results"]
    assert sorted((h["display_name"], h["end_reason"]) for h in history) == [
        ("First Chair", "position_retired"),
        ("First Chair", "replaced"),
        ("Second Chair", "left"),
    ]
    assert set(history[0]) == {"id", "position", "display_name", "started_on", "ended_on", "end_reason"}


def test_committee_fields_retire_and_restore(admin, club, staff):
    field = staff.post(url(club, "fields/"), {"label": "Portfolio", "kind": "text"}, format="json").json()
    change = staff.patch(url(club, f"fields/{field['id']}/"), {"applies_to": "holder"}, format="json")
    assert change.status_code == 400
    assert staff.post(url(club, f"fields/{field['id']}/retire/")).json()["retired_at"]
    assert staff.patch(url(club, f"fields/{field['id']}/"), {"label": "X"}, format="json").status_code == 409
    chair = staff.post(url(club, "positions/"), {"name": "Chair"}, format="json").json()["positions"][0]
    assert chair["values"] == []
    assert staff.post(url(club, f"fields/{field['id']}/restore/")).json()["retired_at"] is None
    assert [f["label"] for f in staff.get(url(club, "fields/")).json()] == ["Portfolio"]
