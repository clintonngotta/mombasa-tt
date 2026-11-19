"""Table bookings (REQ-021, EVAL-021; TASK-036)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from facilities.models import Booking, Table
from notifications.models import Notification

from .helpers import logged_in, make_user
from .test_reservations import _race
from .test_roles import ORGS, add_member, create_club
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db
MINE = "/api/v1/me/table-bookings/"
NAIROBI = ZoneInfo("Africa/Nairobi")


def slot(days=3, hour=10, length=2):
    day = (timezone.now().astimezone(NAIROBI) + timedelta(days=days)).date()
    starts = timezone.datetime(day.year, day.month, day.day, hour, tzinfo=NAIROBI)
    return starts, starts + timedelta(hours=length)


def setup_hall(staff, club):
    venue = make_venue(staff, club, name="Tononoka Hall")
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    hours = [{"weekday": d, "opens": "08:00", "closes": "20:00"} for d in range(7)]
    staff.put(f"{ORGS}{club.id}/venues/{venue['id']}/hours/", {"hours": hours, "closures": []}, format="json")
    return venue


@pytest.fixture
def hall(staff, club):
    return setup_hall(staff, club)


@pytest.fixture
def member(club):
    user = make_user("ama@example.com", display_name="Ama")
    add_member(club, user)
    return user


def tables(hall):
    return list(Table.objects.filter(venue_id=hall["id"]).order_by("position"))


def ask(client, hall, on, expect=201, days=3, hour=10, length=2, **body):
    starts, ends = slot(days, hour, length)
    payload = {
        "venue_id": hall["id"],
        "table_ids": [str(t.id) for t in on],
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        **body,
    }
    response = client.post(MINE, payload, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def staff_url(club, booking, verb):
    return f"{ORGS}{club.id}/bookings/{booking['id']}/{verb}/"


def test_a_request_holds_nothing_and_approval_takes_the_table(staff, club, hall, member):
    me = logged_in(member)
    first = ask(me, hall, tables(hall)[:1], note="Practice with my brother")
    second = ask(me, hall, tables(hall)[:1])  # the same slot: a request blocks nothing
    assert (first["status"], second["status"]) == ("requested", "requested")
    listed = staff.get(f"{ORGS}{club.id}/bookings/", {"status": "requested"}).json()["results"]
    assert len(listed) == 2
    approved = staff.post(staff_url(club, first, "approve"), {"fee_minor": 50000}, format="json").json()
    assert (approved["status"], approved["fee_minor"]) == ("approved", 50000)
    clash = staff.post(staff_url(club, second, "approve"), {}, format="json")
    assert clash.status_code == 409 and clash.json()["code"] == "table_unavailable"
    assert [c["kind"] for c in clash.json()["conflicts"]] == ["booking"]
    # Approving twice changes nothing.
    assert staff.post(staff_url(club, first, "approve"), {}, format="json").json()["status"] == "approved"
    assert [n.title for n in Notification.objects.filter(recipient=member)] == [
        "Your booking at Tononoka Hall is approved"
    ]


def test_closed_times_are_refused(staff, club, hall, member):
    me = logged_in(member)
    assert ask(me, hall, tables(hall)[:1], expect=409, hour=19, length=2)["code"] == "venue_closed"
    starts, _ = slot(days=4)
    day = starts.date().isoformat()
    hours = [{"weekday": d, "opens": "08:00", "closes": "20:00"} for d in range(7)]
    closure = [{"starts_on": day, "ends_on": day, "reason": "Holiday"}]
    staff.put(
        f"{ORGS}{club.id}/venues/{hall['id']}/hours/", {"hours": hours, "closures": closure}, format="json"
    )
    assert ask(me, hall, tables(hall)[:1], expect=409, days=4)["code"] == "venue_closed"
    assert ask(me, hall, tables(hall)[:1], expect=400, days=-2)["code"] == "booking_in_past"


def test_training_and_tournaments_see_approved_bookings(staff, club, hall, member):
    made = ask(logged_in(member), hall, tables(hall)[:1])
    staff.post(staff_url(club, made, "approve"), {}, format="json")
    starts, ends = slot()
    refused = staff.post(
        f"{ORGS}{club.id}/club-sessions/",
        {
            "title": "Squad",
            "table_ids": [str(tables(hall)[0].id)],
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
        },
        format="json",
    )
    assert refused.status_code == 409 and refused.json()["conflicts"][0]["kind"] == "booking"


def test_cancelling_frees_the_slot_and_ended_bookings_stay(staff, club, hall, member):
    me = logged_in(member)
    made = ask(me, hall, tables(hall)[:1])
    staff.post(staff_url(club, made, "approve"), {}, format="json")
    cancelled = me.post(f"{MINE}{made['id']}/cancel/", {"reason": "Can't make it"}, format="json").json()
    assert cancelled["status"] == "cancelled"
    again = ask(me, hall, tables(hall)[:1])
    assert staff.post(staff_url(club, again, "approve"), {}, format="json").json()["status"] == "approved"
    # An ended booking can't be cancelled and stays listed.
    Booking.objects.filter(pk=again["id"]).update(
        starts_at=timezone.now() - timedelta(hours=3), ends_at=timezone.now() - timedelta(hours=1)
    )
    assert me.post(f"{MINE}{again['id']}/cancel/", {}, format="json").json()["code"] == "booking_over"
    assert [b["status"] for b in me.get(MINE).json()["results"]] == ["cancelled", "approved"]


def test_rejection_needs_a_reason_and_only_staff_decide(staff, club, hall, member):
    me = logged_in(member)
    made = ask(me, hall, tables(hall)[:1])
    assert me.post(staff_url(club, made, "approve"), {}, format="json").status_code == 403
    assert staff.post(staff_url(club, made, "reject"), {}, format="json").json()["code"] == "reason_required"
    rejected = staff.post(
        staff_url(club, made, "reject"), {"reason": "Tournament setup"}, format="json"
    ).json()
    assert (rejected["status"], rejected["reason"]) == ("rejected", "Tournament setup")
    outsider = logged_in(make_user("x@example.com"))
    assert ask(outsider, hall, tables(hall)[:1], expect=404)  # not their club, not a public facility
    assert outsider.post(f"{MINE}{made['id']}/cancel/", {}, format="json").status_code == 404


@pytest.mark.django_db(transaction=True)
def test_two_approvals_racing_for_one_slot_take_it_once():
    admin = make_user("admin@example.com", display_name="Club Admin")
    club = create_club(admin)
    staff = logged_in(admin)
    hall = setup_hall(staff, club)
    member = make_user("ama@example.com", display_name="Ama")
    add_member(club, member)
    cache.clear()
    me = logged_in(member)
    clients = [logged_in(admin), logged_in(admin)]
    for round_number in range(5):
        a = ask(me, hall, tables(hall)[:1], days=3 + round_number)
        b = ask(me, hall, tables(hall)[:1], days=3 + round_number)
        replies = _race(
            [
                lambda c=clients[0], x=a: c.post(staff_url(club, x, "approve"), {}, format="json"),
                lambda c=clients[1], x=b: c.post(staff_url(club, x, "approve"), {}, format="json"),
            ]
        )
        assert sorted(s for s, _ in replies) == [200, 409], (round_number, replies)
    assert Booking.objects.filter(status="approved").count() == 5
