"""Apologies (REQ-052, REQ-046; TASK-126): sent before the start with an optional reason, seen by staff,
and shown as apologised rather than absent in attendance."""

from datetime import timedelta

import pytest
from django.utils import timezone

from regions.models import Meeting, MeetingInvitee
from training.models import ClubSession, SessionInvitation

from .test_club_sessions import MINE, invitation_of
from .test_meeting_penalties import RULES, invitee_id, meeting_url, people, soon  # noqa: F401
from .test_training_check_in import check_in, hall, starting, world  # noqa: F401

pytestmark = pytest.mark.django_db


def apologise(client, invitation, **body):
    return client.post(f"{MINE}{invitation.id}/apologise/", body, format="json")


def test_a_training_apology_is_sent_before_the_start(world):  # noqa: F811
    club, session = world["club"], world["session"]
    ann = invitation_of(world["users"]["ann"], session)
    ben = invitation_of(world["users"]["ben"], session)
    world["ann"].post(f"{MINE}{ann.id}/accept/", {}, format="json")

    sent = apologise(world["ann"], ann, reason="Exam on Wednesday")
    assert sent.status_code == 200, sent.json()
    assert (sent.json()["status"], sent.json()["apologised"], sent.json()["apology_reason"]) == (
        "declined",
        True,
        "Exam on Wednesday",
    )
    # The reason is optional, another member can't send it for you, and unknown fields are refused.
    assert apologise(world["ben"], ann).status_code == 404
    assert apologise(world["ann"], ann, note="x").status_code == 400
    assert apologise(world["ann"], ann, reason="x" * 301).status_code == 400

    # Staff see the apology and its reason; a plain decline is not an apology.
    world["ben"].post(f"{MINE}{ben.id}/decline/", {}, format="json")
    path = f"/api/v1/organizations/{club.id}/club-sessions/{session['id']}/invitations/"
    rows = {row["display_name"]: row for row in world["coach"].get(path).json()}
    assert (rows["Ann"]["apologised"], rows["Ann"]["apology_reason"]) == (True, "Exam on Wednesday")
    assert (rows["Ben"]["apologised"], rows["Ben"]["apology_reason"]) == (False, "")

    # Marked absent, Ann still shows as apologised rather than only absent.
    starting(session, -5)
    marked = world["coach"].patch(f"{path}{ann.id}/", {"attended": False}, format="json").json()
    assert (marked["attended"], marked["apologised"]) == (False, True)
    # After the start it is too late to apologise, and someone who apologised doesn't check in.
    late = apologise(world["ben"], ben, reason="Stuck in traffic")
    assert late.status_code == 409 and late.json()["code"] == "apology_too_late"
    assert SessionInvitation.objects.get(pk=ben.pk).apologised_at is None


def test_coming_after_all_withdraws_the_apology(world):  # noqa: F811
    ann = invitation_of(world["users"]["ann"], world["session"])
    apologise(world["ann"], ann, reason="Away")
    again = apologise(world["ann"], ann, reason="Still away")  # sending again changes the reason
    assert again.json()["apology_reason"] == "Still away"
    back = world["ann"].post(f"{MINE}{ann.id}/accept/", {}, format="json").json()
    assert (back["status"], back["apologised"], back["apology_reason"]) == ("accepted", False, "")
    starting(world["session"], 5)
    assert check_in(world["ann"], ann).status_code == 200

    ClubSession.objects.filter(pk=world["session"]["id"]).update(status="cancelled")
    assert apologise(world["ann"], ann).json()["code"] == "session_cancelled"


def test_a_meeting_apology_carries_a_reason_and_stops_at_the_start(club, people):  # noqa: F811
    made = (
        people["officer"]
        .post(
            meeting_url(club),
            {"title": "AGM", "audience": "members", "starts_at": soon(2), "ends_at": soon(4), "rules": RULES},
            format="json",
        )
        .json()
    )
    people["officer"].post(meeting_url(club, made["id"], "publish/"), format="json")
    answer = meeting_url(club, made["id"], "answer/")
    sorry = people["sorry"].post(answer, {"answer": "apologies", "reason": "Travelling"}, format="json")
    assert sorry.status_code == 200, sorry.json()
    assert (sorry.json()["me"]["answer"], sorry.json()["me"]["apology_reason"]) == ("apologies", "Travelling")
    assert people["sorry"].post(answer, {"answer": "apologies", "why": "x"}, format="json").status_code == 400

    # Staff see the reason; another invitee doesn't see anyone's.
    seen = people["officer"].get(meeting_url(club, made["id"])).json()
    reasons = {row["display_name"]: row["apology_reason"] for row in seen["invitees"]}
    assert reasons["Sorry"] == "Travelling" and reasons["Present"] == ""
    assert "Travelling" not in str(people["present"].get(meeting_url(club, made["id"])).json())

    # Changing to attending clears it; apologising again before the start is fine.
    cleared = people["sorry"].post(answer, {"answer": "attending"}, format="json").json()["me"]
    assert (cleared["answer"], cleared["apology_reason"], cleared["apologised_at"]) == ("attending", "", None)
    people["sorry"].post(answer, {"answer": "apologies", "reason": "Travelling"}, format="json")

    # Once it has started an apology is too late, though "attending" can still be said.
    Meeting.objects.filter(pk=made["id"]).update(starts_at=timezone.now() - timedelta(minutes=5))
    late = people["late"].post(answer, {"answer": "apologies", "reason": "Traffic"}, format="json")
    assert late.status_code == 409 and late.json()["code"] == "apology_too_late"
    assert people["late"].post(answer, {"answer": "attending"}, format="json").status_code == 200

    # When it is over, whoever apologised is recorded as apologies, the silent one as absent.
    Meeting.objects.filter(pk=made["id"]).update(ends_at=timezone.now() - timedelta(minutes=1))
    people["officer"].post(meeting_url(club, made["id"], "penalties/"), format="json")
    record = dict(
        MeetingInvitee.objects.filter(meeting_id=made["id"]).values_list("user__display_name", "attendance")
    )
    assert record["Sorry"] == "apologies" and record["Absent"] == "absent"
    assert MeetingInvitee.objects.get(pk=invitee_id(club, made, "sorry")).apology_reason == "Travelling"
