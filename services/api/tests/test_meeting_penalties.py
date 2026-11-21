"""Meeting rules and penalties (REQ-046): staff set what missing a meeting costs, the secretary takes
attendance, penalties are issued from the record once the meeting is over, and from then on only the host's
admin changes them."""

from datetime import timedelta

import pytest
from django.utils import timezone

from organizations.models import Role
from regions.models import Meeting, MeetingInvitee, MeetingPenalty

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db

RULES = [
    {"applies_to": "absent", "penalty": "Fine for missing the meeting", "amount_minor": 50000},
    {"applies_to": "late", "penalty": "Fine for arriving late", "amount_minor": 20000},
]


def soon(hours):
    return (timezone.now() + timedelta(hours=hours)).isoformat()


@pytest.fixture
def people(club, admin):
    """The club admin; a governance officer (not admin); a secretary and three more members."""
    governance = Role.objects.create(organization=club, name="Governance", permissions=["governance.manage"])
    users = {
        name: make_user(f"{name}@example.com", display_name=name.title())
        for name in ("officer", "secretary", "present", "late", "absent", "sorry")
    }
    add_member(club, users["officer"], governance)
    for name in ("secretary", "present", "late", "absent", "sorry"):
        add_member(club, users[name])
    return {
        "admin": logged_in(admin),
        **{name: logged_in(user) for name, user in users.items()},
        "users": users,
    }


def meeting_url(club, meeting_id="", path=""):
    return f"{ORGS}{club.id}/meetings/" + (f"{meeting_id}/{path}" if meeting_id else "")


def held(club, people) -> dict:
    """A published members' meeting with rules and a secretary, now in progress."""
    made = people["officer"].post(
        meeting_url(club),
        {
            "title": "AGM",
            "kind": "general",
            "audience": "members",
            "starts_at": soon(2),
            "ends_at": soon(4),
            "agenda": [{"title": "Accounts"}],
            "rules": RULES,
            "secretary_id": str(people["users"]["secretary"].id),
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    meeting = made.json()
    assert (
        meeting["secretary"]["display_name"] == "Secretary" and meeting["rules"][0]["amount_minor"] == 50000
    )
    people["officer"].post(meeting_url(club, meeting["id"], "publish/"), format="json")
    people["sorry"].post(meeting_url(club, meeting["id"], "answer/"), {"answer": "apologies"}, format="json")
    Meeting.objects.filter(pk=meeting["id"]).update(starts_at=timezone.now() - timedelta(minutes=30))
    return meeting


def invitee_id(club, meeting, name):
    return str(MeetingInvitee.objects.get(meeting_id=meeting["id"], user__email=f"{name}@example.com").id)


def test_rules_are_validated_and_shown_to_invitees(club, people):
    twice = people["officer"].post(
        meeting_url(club),
        {"title": "x", "starts_at": soon(2), "ends_at": soon(3), "rules": [RULES[0], RULES[0]]},
        format="json",
    )
    assert twice.status_code == 400 and "rules" in twice.json()["fields"]
    stranger = make_user("stranger@example.com")
    outside = people["officer"].post(
        meeting_url(club),
        {"title": "x", "starts_at": soon(2), "ends_at": soon(3), "secretary_id": str(stranger.id)},
        format="json",
    )
    assert outside.status_code == 400 and "secretary_id" in outside.json()["fields"]
    # Without a secretary named, whoever calls the meeting takes the minutes.
    plain = (
        people["officer"]
        .post(meeting_url(club), {"title": "x", "starts_at": soon(2), "ends_at": soon(3)}, format="json")
        .json()
    )
    assert plain["secretary"]["display_name"] == "Officer"

    meeting = held(club, people)
    seen = people["present"].get(meeting_url(club, meeting["id"])).json()
    assert [rule["applies_to"] for rule in seen["rules"]] == ["absent", "late"]
    assert (
        seen["invitees"] == []
        and seen["can_take_attendance"] is False
        and seen["can_edit_penalties"] is False
    )


def test_the_secretary_takes_attendance_and_penalties_follow_the_rules(club, people):
    meeting = held(club, people)
    path = meeting_url(club, meeting["id"])
    people["present"].post(path + "check-in/", format="json")

    secretary_view = people["secretary"].get(path).json()
    assert secretary_view["can_take_attendance"] is True and len(secretary_view["invitees"]) == 7
    mark = {"invitee": invitee_id(club, meeting, "late"), "attendance": "late"}
    # A member who isn't the secretary can't mark anyone.
    assert people["absent"].post(path + "attendance/", mark, format="json").status_code == 403
    marked = people["secretary"].post(path + "attendance/", mark, format="json")
    assert marked.status_code == 200, marked.json()
    marks = {i["display_name"]: i["attendance"] for i in marked.json()["invitees"]}
    assert marks["Present"] == "present" and marks["Late"] == "late" and marks["Absent"] == ""

    # Not while it is still running.
    assert people["secretary"].post(path + "penalties/", format="json").status_code == 409
    Meeting.objects.filter(pk=meeting["id"]).update(
        starts_at=timezone.now() - timedelta(hours=3), ends_at=timezone.now() - timedelta(hours=1)
    )
    issued = people["secretary"].post(path + "penalties/", format="json")
    assert issued.status_code == 200, issued.json()
    record = {i["display_name"]: (i["attendance"], i["penalty"]) for i in issued.json()["invitees"]}
    assert record["Present"] == ("present", None)
    assert record["Sorry"] == ("apologies", None)  # apologies sent, and no rule for apologies
    assert record["Late"][0] == "late" and record["Late"][1]["amount_minor"] == 20000
    assert record["Absent"][0] == "absent"  # nobody marked them: absent
    assert record["Absent"][1]["penalty"] == "Fine for missing the meeting"
    assert record["Absent"][1]["status"] == "issued"
    # The player sees their own penalty.
    mine = people["absent"].get(path).json()["me"]
    assert mine["attendance"] == "absent" and mine["penalty"]["amount_minor"] == 50000

    # Issuing again adds nothing; a mark with a penalty can't be changed by the secretary.
    count = MeetingPenalty.objects.count()
    people["secretary"].post(path + "penalties/", format="json")
    assert MeetingPenalty.objects.count() == count
    changed = people["secretary"].post(
        path + "attendance/",
        {"invitee": invitee_id(club, meeting, "absent"), "attendance": "present"},
        format="json",
    )
    assert changed.status_code == 409 and changed.json()["code"] == "penalty_issued"


def test_only_the_admin_changes_an_issued_penalty(club, people):
    meeting = held(club, people)
    path = meeting_url(club, meeting["id"])
    Meeting.objects.filter(pk=meeting["id"]).update(
        starts_at=timezone.now() - timedelta(hours=3), ends_at=timezone.now() - timedelta(hours=1)
    )
    issued = people["officer"].post(path + "penalties/", format="json").json()
    penalty = next(i["penalty"] for i in issued["invitees"] if i["display_name"] == "Absent")
    edit = f"{path}penalties/{penalty['id']}/"
    waive = {"status": "waived", "note": "Was in hospital"}
    for refused in ("officer", "secretary", "absent"):
        assert people[refused].patch(edit, waive, format="json").status_code == 403
    assert people["admin"].get(path).json()["can_edit_penalties"] is True
    done = people["admin"].patch(edit, waive, format="json")
    assert done.status_code == 200, done.json()
    assert done.json()["status"] == "waived" and done.json()["note"] == "Was in hospital"
    (change,) = done.json()["history"]
    assert change["by_name"] == "Club Admin" and change["changes"]["status"] == ["issued", "waived"]
    lowered = people["admin"].patch(edit, {"amount_minor": 10000, "status": "paid"}, format="json").json()
    assert lowered["amount_minor"] == 10000 and len(lowered["history"]) == 2
    assert people["absent"].get(path).json()["me"]["penalty"]["status"] == "paid"


def test_a_meeting_without_rules_issues_nothing_and_others_stay_out(club, people):
    meeting = (
        people["officer"]
        .post(
            meeting_url(club),
            {"title": "Chat", "audience": "members", "starts_at": soon(2), "ends_at": soon(3)},
            format="json",
        )
        .json()
    )
    path = meeting_url(club, meeting["id"])
    mark = {"invitee": "00000000-0000-0000-0000-000000000000", "attendance": "present"}
    assert people["officer"].post(path + "attendance/", mark, format="json").status_code == 409  # draft
    people["officer"].post(path + "publish/", format="json")
    assert people["officer"].post(path + "attendance/", mark, format="json").status_code == 409  # not started
    Meeting.objects.filter(pk=meeting["id"]).update(
        starts_at=timezone.now() - timedelta(hours=3), ends_at=timezone.now() - timedelta(hours=1)
    )
    assert people["officer"].post(path + "attendance/", mark, format="json").status_code == 404
    refused = people["officer"].post(path + "penalties/", format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "no_rules"
    outsider = logged_in(make_user("outsider@example.com"))
    assert outsider.post(path + "penalties/", format="json").status_code == 404
