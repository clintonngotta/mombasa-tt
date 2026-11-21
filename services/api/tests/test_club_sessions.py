"""Club training sessions (REQ-027, EVAL-027; TASK-044)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from coaching.models import Booking
from facilities.models import Table
from training.models import ClubSession, PlanItem, SessionInvitation, TrainingPlan

from .helpers import logged_in, make_user
from .test_reservations import _race
from .test_roles import ORGS, add_member, create_club
from .test_tournaments import do, make_tournament
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db
MINE = "/api/v1/me/session-invitations/"


def sessions_url(club, session=None, tail=""):
    return f"{ORGS}{club.id}/club-sessions/" + (f"{session['id']}/" if session else "") + tail


def soon(hours=24, length=2):
    starts = (timezone.now() + timedelta(hours=hours)).replace(microsecond=0)
    return starts, starts + timedelta(hours=length)


def schedule(staff, club, tables, expect=201, hours=24, length=2, **body):
    starts, ends = soon(hours, length)
    payload = {
        "title": "Tuesday squad",
        "table_ids": [str(t.id) for t in tables],
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        **body,
    }
    response = staff.post(sessions_url(club), payload, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def invite(staff, club, session, *users, expect=200):
    response = staff.post(
        sessions_url(club, session, "invitations/"), {"user_ids": [str(u.id) for u in users]}, format="json"
    )
    assert response.status_code == expect, response.json()
    return response.json()


def invitation_of(user, session):
    return SessionInvitation.objects.get(user=user, session_id=session["id"])


def answer(client, invitation, verb, expect=200):
    response = client.post(f"{MINE}{invitation.id}/{verb}/", {}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


@pytest.fixture
def tables(hall):
    return list(Table.objects.filter(venue_id=hall["id"]).order_by("position"))


@pytest.fixture
def amina(club):
    user = make_user("amina@example.com", display_name="Amina")
    add_member(club, user)
    return user


def test_staff_schedule_invite_and_a_member_accepts_once(staff, club, tables, amina):
    session = schedule(staff, club, tables[:1], capacity=8)
    assert (session["status"], session["invited"], session["accepted"]) == ("scheduled", 0, 0)
    assert [t["label"] for t in session["tables"]] == ["Table 1"]
    invited = invite(staff, club, session, amina)
    assert [(i["display_name"], i["status"]) for i in invited] == [("Amina", "invited")]
    # Inviting again keeps the one invitation.
    assert len(invite(staff, club, session, amina)) == 1
    member = logged_in(amina)
    listed = member.get(MINE).json()["results"]
    assert [(i["status"], i["session"]["title"]) for i in listed] == [("invited", "Tuesday squad")]
    invitation = invitation_of(amina, session)
    assert answer(member, invitation, "accept")["status"] == "accepted"
    # Accepting twice is harmless.
    assert answer(member, invitation, "accept")["status"] == "accepted"
    assert staff.get(sessions_url(club, session)).json()["accepted"] == 1
    assert answer(member, invitation, "decline")["status"] == "declined"
    assert staff.get(sessions_url(club, session)).json()["accepted"] == 0


def test_an_invitation_holds_nothing_until_it_is_accepted(staff, club, tables, amina):
    session = schedule(staff, club, tables[:1])
    invite(staff, club, session, amina)
    member = logged_in(amina)
    plan = member.post("/api/v1/me/training-plans/", {"title": "Serve"}, format="json").json()
    item = {
        "kind": "session",
        "title": "Serve practice",
        "starts_at": session["starts_at"],
        "ends_at": session["ends_at"],
    }
    # Only invited: the member's own session can take that time.
    made = member.post(f"/api/v1/me/training-plans/{plan['id']}/items/", item, format="json")
    assert made.status_code == 201, made.json()
    refused = answer(member, invitation_of(amina, session), "accept", expect=409)
    assert refused["code"] == "calendar_conflict"
    assert [c["kind"] for c in refused["conflicts"]] == ["training"]
    # Once the personal session moves away, accepting holds the time, and the time is then taken.
    PlanItem.objects.filter(plan__owner=amina, kind="session").delete()
    answer(member, invitation_of(amina, session), "accept")
    again = member.post(f"/api/v1/me/training-plans/{plan['id']}/items/", item, format="json")
    assert again.status_code == 409
    assert [c["kind"] for c in again.json()["conflicts"]] == ["club_session"]
    # A checklist item is not a reservation.
    tick = member.post(
        f"/api/v1/me/training-plans/{plan['id']}/items/",
        {"kind": "checklist", "title": "Shadow play"},
        format="json",
    )
    assert tick.status_code == 201
    assert TrainingPlan.objects.filter(owner=amina).count() == 1


def test_a_coaching_booking_in_the_way_is_reported_before_accepting(staff, club, tables, amina):
    session = schedule(staff, club, tables[:1])
    invite(staff, club, session, amina)
    coach = make_user("coach@example.com", display_name="Coach Kai")
    Booking.objects.create(
        coach=coach,
        trainee=amina,
        starts_at=session["starts_at"],
        ends_at=session["ends_at"],
        status=Booking.Status.CONFIRMED,
    )
    refused = answer(logged_in(amina), invitation_of(amina, session), "accept", expect=409)
    assert [c["kind"] for c in refused["conflicts"]] == ["booking"]


def test_a_table_in_use_is_reported_before_the_session_is_saved(staff, club, tables, hall):
    first = schedule(staff, club, tables[:1])
    clash = schedule(staff, club, tables, expect=409, hours=25)
    assert clash["code"] == "table_unavailable"
    assert [(c["kind"], c["title"], c["tables"]) for c in clash["conflicts"]] == [
        ("club_session", "Tuesday squad", ["Table 1"])
    ]
    # The other table is free, and right after the first session is free too.
    schedule(staff, club, tables[1:], hours=25)
    schedule(staff, club, tables[:1], hours=26)
    # Cancelling frees the table.
    assert staff.post(sessions_url(club, first, "cancel/"), {}, format="json").json()["status"] == "cancelled"
    schedule(staff, club, tables[:1], hours=24, length=1)


def test_a_running_tournament_at_the_venue_takes_its_tables(staff, club, tables, hall):
    starts, _ = soon(24 * 3)
    # The tournament's own day: late in the UTC evening it is already tomorrow in Nairobi.
    day = starts.astimezone(ZoneInfo("Africa/Nairobi")).date().isoformat()
    cup = make_tournament(staff, club, hall, starts_on=day, ends_on=day, timezone="Africa/Nairobi")
    # A draft takes nothing.
    schedule(staff, club, tables[:1], hours=24 * 3)
    ClubSession.objects.all().delete()
    from .test_tournaments import add_event

    add_event(staff, cup)
    do(staff, cup, "publish")
    clash = schedule(staff, club, tables[:1], expect=409, hours=24 * 3)
    assert [c["kind"] for c in clash["conflicts"]] == ["tournament"]


def test_capacity_and_concurrent_acceptances(staff, club, tables, amina):
    brian = make_user("brian@example.com", display_name="Brian")
    add_member(club, brian)
    session = schedule(staff, club, tables[:1], capacity=1)
    invite(staff, club, session, amina, brian)
    answer(logged_in(amina), invitation_of(amina, session), "accept")
    assert (
        answer(logged_in(brian), invitation_of(brian, session), "accept", expect=409)["code"]
        == "session_full"
    )
    assert [i["session"]["full"] for i in logged_in(brian).get(MINE).json()["results"]] == [True]
    # Staff can't shrink capacity below those already in.
    response = staff.patch(sessions_url(club, session), {"capacity": 1}, format="json")
    assert response.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_two_acceptances_of_the_same_hour_never_both_hold_it():
    """EVAL-027: a member accepts two overlapping sessions at the same instant; one wins every time."""
    admin = make_user("admin@example.com", display_name="Club Admin")
    club = create_club(admin)
    staff = logged_in(admin)
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    one, two = Table.objects.filter(venue_id=venue["id"]).order_by("position")
    amina = make_user("amina@example.com", display_name="Amina")
    add_member(club, amina)
    cache.clear()
    clients = [logged_in(amina), logged_in(amina)]
    for round_number in range(10):
        a = schedule(staff, club, [one], hours=24 + 3 * round_number, title="A")
        b = schedule(staff, club, [two], hours=24 + 3 * round_number, title="B")
        invite(staff, club, a, amina)
        invite(staff, club, b, amina)
        replies = _race(
            [
                lambda c=clients[0], s=a: c.post(
                    f"{MINE}{invitation_of(amina, s).id}/accept/", {}, format="json"
                ),
                lambda c=clients[1], s=b: c.post(
                    f"{MINE}{invitation_of(amina, s).id}/accept/", {}, format="json"
                ),
            ]
        )
        assert sorted(status for status, _ in replies) == [200, 409], (round_number, replies)
    assert SessionInvitation.objects.filter(status="accepted").count() == 10


def test_attendance_is_one_mark_however_often_recorded(staff, club, tables, amina):
    session = schedule(staff, club, tables[:1], hours=1)
    invite(staff, club, session, amina)
    invitation = invitation_of(amina, session)
    path = sessions_url(club, session, f"invitations/{invitation.id}/")
    early = staff.patch(path, {"attended": True}, format="json")
    assert early.status_code == 409 and early.json()["code"] == "session_not_started"
    ClubSession.objects.filter(pk=session["id"]).update(
        starts_at=timezone.now() - timedelta(minutes=30), ends_at=timezone.now() + timedelta(minutes=90)
    )
    for _ in range(2):
        marked = staff.patch(path, {"attended": True}, format="json").json()
        assert marked["attended"] is True
    invitation.refresh_from_db()
    first_mark = invitation.attendance_at
    staff.patch(path, {"attended": True}, format="json")
    invitation.refresh_from_db()
    assert invitation.attendance_at == first_mark
    assert SessionInvitation.objects.filter(session_id=session["id"]).count() == 1
    # The member sees their own mark.
    mine = logged_in(amina).get(MINE).json()["results"]
    assert mine[0]["attended"] is True


def test_only_training_staff_run_sessions_and_only_members_are_invited(staff, club, tables, amina):
    session = schedule(staff, club, tables[:1])
    member = logged_in(amina)
    assert member.get(sessions_url(club)).status_code == 403
    assert member.post(sessions_url(club), {}, format="json").status_code == 403
    assert member.get(sessions_url(club, session, "invitations/")).status_code == 403
    outsider = make_user("outsider@example.com")
    assert invite(staff, club, session, outsider, expect=400)["code"] == "not_members"
    # Another club's tables can't be used.
    other_admin = make_user("other@example.com", display_name="Other Admin")
    other = create_club(other_admin, name="Kisauni TT")
    theirs = make_venue(logged_in(other_admin), other, name="Kisauni Hall")
    add_table(logged_in(other_admin), other, theirs, "Their table")
    foreign = Table.objects.get(venue_id=theirs["id"])
    refused = schedule(staff, club, [foreign], expect=400)
    assert "table_ids" in refused["fields"]
    # Someone else's invitation is not found.
    invite(staff, club, session, amina)
    assert logged_in(outsider).post(f"{MINE}{invitation_of(amina, session).id}/accept/").status_code == 404


def test_a_cancelled_session_frees_members_and_refuses_answers(staff, club, tables, amina):
    session = schedule(staff, club, tables[:1])
    invite(staff, club, session, amina)
    member = logged_in(amina)
    answer(member, invitation_of(amina, session), "accept")
    # Members are in: the session can't move, only be cancelled.
    later = soon(30)
    moved = staff.patch(
        sessions_url(club, session),
        {"starts_at": later[0].isoformat(), "ends_at": later[1].isoformat()},
        format="json",
    )
    assert moved.status_code == 409 and moved.json()["code"] == "session_has_members"
    staff.post(sessions_url(club, session, "cancel/"), {}, format="json")
    assert answer(member, invitation_of(amina, session), "accept")["status"] == "accepted"  # unchanged
    plan = member.post("/api/v1/me/training-plans/", {"title": "Serve"}, format="json").json()
    item = {
        "kind": "session",
        "title": "Solo",
        "starts_at": session["starts_at"],
        "ends_at": session["ends_at"],
    }
    assert (
        member.post(f"/api/v1/me/training-plans/{plan['id']}/items/", item, format="json").status_code == 201
    )
