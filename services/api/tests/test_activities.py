"""Club activities, RSVPs and the club schedule (REQ-039, EVAL-039; TASK-072)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from activities.models import Activity, Rsvp
from organizations.models import Role

from .helpers import logged_in, make_user
from .test_reservations import _race
from .test_roles import ORGS, add_member, create_club
from .test_tournaments import do, make_tournament
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


def url(club, activity=None, tail=""):
    return f"{ORGS}{club.id}/activities/" + (f"{activity['id']}/" if activity else "") + tail


def when(days=3, hours=3):
    starts = (timezone.now() + timedelta(days=days)).replace(microsecond=0)
    return starts.isoformat(), (starts + timedelta(hours=hours)).isoformat()


def create(client, club, expect=201, **body):
    starts, ends = when()
    payload = {
        "title": "Night out",
        "kind": "social",
        "starts_at": starts,
        "ends_at": ends,
        "place": "Old Town",
        **body,
    }
    response = client.post(url(club), payload, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def rsvp(client, club, activity, answer, expect=200):
    response = client.post(url(club, activity, "rsvp/"), {"answer": answer}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


@pytest.fixture
def officer(club):
    role = Role.objects.create(organization=club, name="Social", permissions=["activities.manage"])
    user = make_user("officer@example.com", display_name="Officer")
    add_member(club, user, role)
    return logged_in(user)


@pytest.fixture
def members(club):
    made = {}
    for name in "ABCD":
        user = make_user(f"{name.lower()}@example.com", display_name=f"Member {name}")
        add_member(club, user)
        made[name] = user
    return made


def test_drafts_stay_with_staff_until_published(officer, club, members):
    draft = create(officer, club, capacity=2, cost_note="KES 500 each, pay on the night")
    a = logged_in(members["A"])
    assert a.get(url(club)).json()["results"] == []
    assert a.get(url(club, draft)).status_code == 404
    assert rsvp(a, club, draft, "going", expect=404)
    assert a.post(url(club), {}, format="json").status_code == 403
    published = officer.post(url(club, draft, "publish/"), {}, format="json").json()
    assert published["status"] == "published" and published["published_at"]
    seen = a.get(url(club)).json()["results"]
    assert [(x["title"], x["can_answer"], x["cost_note"]) for x in seen] == [
        ("Night out", True, "KES 500 each, pay on the night")
    ]
    assert "paid" not in str(seen[0]).lower().replace("pay on the night", "")


@pytest.mark.django_db(transaction=True)
def test_three_going_at_once_for_two_places_waitlists_one():
    admin = make_user("admin@example.com", display_name="Club Admin")
    club = create_club(admin)
    staff = logged_in(admin)
    users = []
    for name in "ABC":
        user = make_user(f"{name.lower()}@example.com", display_name=f"Member {name}")
        add_member(club, user)
        users.append(user)
    cache.clear()
    clients = [logged_in(user) for user in users]
    for round_number in range(5):
        activity = create(staff, club, capacity=2, title=f"Round {round_number}")
        staff.post(url(club, activity, "publish/"), {}, format="json")
        path = url(club, activity, "rsvp/")
        replies = _race([lambda c=c, p=path: c.post(p, {"answer": "going"}, format="json") for c in clients])
        assert [s for s, _ in replies] == [200, 200, 200]
        answers = Rsvp.objects.filter(activity_id=activity["id"])
        assert answers.filter(waitlisted=False).count() == 2, round_number
        assert answers.filter(waitlisted=True).count() == 1


def test_a_freed_place_is_not_handed_on_by_itself(officer, club, members):
    activity = create(officer, club, capacity=1)
    officer.post(url(club, activity, "publish/"), {}, format="json")
    a, b = logged_in(members["A"]), logged_in(members["B"])
    assert rsvp(a, club, activity, "going")["my_waitlisted"] is False
    shown = rsvp(b, club, activity, "going")
    assert (shown["my_answer"], shown["my_waitlisted"], shown["going"], shown["waitlisted"]) == (
        "going",
        True,
        1,
        1,
    )
    rsvp(a, club, activity, "not_going")
    # B is still waiting until they answer again.
    assert Rsvp.objects.get(user=members["B"]).waitlisted is True
    assert rsvp(b, club, activity, "going")["my_waitlisted"] is False
    # Answering going twice keeps the place.
    assert rsvp(b, club, activity, "going")["going"] == 1
    # Capacity can't drop below who's going.
    assert officer.patch(url(club, activity), {"capacity": 1}, format="json").status_code == 200


def test_changes_and_cancellation_keep_the_record(officer, club, members):
    activity = create(officer, club)
    officer.post(url(club, activity, "publish/"), {}, format="json")
    rsvp(logged_in(members["A"]), club, activity, "maybe")
    moved = officer.patch(url(club, activity), {"place": "Fort Jesus gate"}, format="json").json()
    assert moved["place"] == "Fort Jesus gate"
    assert (
        officer.post(url(club, activity, "cancel/"), {}, format="json").status_code == 400
    )  # a reason is needed
    cancelled = officer.post(url(club, activity, "cancel/"), {"reason": "Heavy rain"}, format="json").json()
    assert (cancelled["status"], cancelled["cancel_reason"]) == ("cancelled", "Heavy rain")
    assert Rsvp.objects.filter(activity_id=activity["id"]).count() == 1
    assert rsvp(logged_in(members["A"]), club, activity, "going", expect=409)["code"] == "activity_closed"
    assert officer.patch(url(club, activity), {"place": "x"}, format="json").status_code == 409
    assert logged_in(members["B"]).get(url(club, activity)).json()["status"] == "cancelled"


def test_selected_audience_attendees_and_deadline(officer, club, members):
    outsider = logged_in(make_user("e@example.com", display_name="Outsider E"))
    refused = create(officer, club, expect=400, audience="selected")
    assert "invitee_ids" in refused["fields"]
    assert create(
        officer, club, expect=400, audience="selected", invitee_ids=[str(make_user("x@example.com").id)]
    )
    picked = create(
        officer, club, audience="selected", invitee_ids=[str(members["A"].id), str(members["B"].id)]
    )
    officer.post(url(club, picked, "publish/"), {}, format="json")
    a, c = logged_in(members["A"]), logged_in(members["C"])
    assert [x["id"] for x in a.get(url(club)).json()["results"]] == [picked["id"]]
    assert c.get(url(club)).json()["results"] == []
    assert rsvp(c, club, picked, "going", expect=404)
    rsvp(a, club, picked, "going")
    rsvp(logged_in(members["B"]), club, picked, "not_going")
    attendees = a.get(url(club, picked, "attendees/")).json()
    assert attendees == [{"display_name": "Member A", "answer": "going", "waitlisted": False}]
    assert outsider.get(url(club, picked, "attendees/")).status_code == 404
    assert officer.get(url(club, picked, "invitees/")).json()["invitee_ids"]
    assert a.get(url(club, picked, "invitees/")).status_code == 403
    # Past the deadline, answers close.
    closed = create(officer, club, rsvp_deadline=(timezone.now() + timedelta(hours=1)).isoformat())
    officer.post(url(club, closed, "publish/"), {}, format="json")
    Activity.objects.filter(pk=closed["id"]).update(rsvp_deadline=timezone.now() - timedelta(minutes=1))
    assert rsvp(a, club, closed, "going", expect=409)["code"] == "rsvp_closed"


def test_public_activities_reach_everyone_signed_in_but_answers_stay_with_members(officer, club, members):
    open_day = create(officer, club, title="Open day", kind="open_day", public=True)
    private = create(officer, club, title="Members' night")
    for made in (open_day, private):
        officer.post(url(club, made, "publish/"), {}, format="json")
    outsider = logged_in(make_user("e@example.com", display_name="Outsider E"))
    seen = outsider.get(url(club)).json()["results"]
    assert [(x["title"], x["can_answer"]) for x in seen] == [("Open day", False)]
    assert rsvp(outsider, club, open_day, "going", expect=403)["code"] == "not_invited"
    assert outsider.get(url(club, private)).status_code == 404


def test_the_schedule_merges_activities_tournaments_and_training_in_order(officer, club, members, staff):
    soon_starts, soon_ends = when(days=1)
    later = create(
        officer, club, title="Fun day", kind="fun_day", starts_at=when(days=5)[0], ends_at=when(days=5)[1]
    )
    early = create(officer, club, title="Practice", kind="practice", starts_at=soon_starts, ends_at=soon_ends)
    create(officer, club, title="Still a draft")
    for made in (later, early):
        officer.post(url(club, made, "publish/"), {}, format="json")
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    nairobi = ZoneInfo("Africa/Nairobi")
    day = (timezone.now().astimezone(nairobi) + timedelta(days=3)).date().isoformat()
    cup = make_tournament(staff, club, venue, starts_on=day, ends_on=day, timezone="Africa/Nairobi")
    from .test_tournaments import add_event

    add_event(staff, cup)
    do(staff, cup, "publish")
    from facilities.models import Table

    table = Table.objects.get(venue_id=venue["id"])
    # Mid-morning in Nairobi, two days on, so the session never runs past midnight whenever this runs.
    two_days = (timezone.now().astimezone(nairobi) + timedelta(days=2)).date()
    starts = datetime(two_days.year, two_days.month, two_days.day, 10, tzinfo=nairobi)
    staff.post(
        f"{ORGS}{club.id}/club-sessions/",
        {
            "title": "Squad",
            "table_ids": [str(table.id)],
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
        },
        format="json",
    )
    a = logged_in(members["A"])
    items = a.get(f"{ORGS}{club.id}/schedule/").json()
    assert [(i["kind"], i["title"]) for i in items] == [
        ("activity", "Practice"),
        ("training", "Squad"),
        ("tournament", "Coast Open"),
        ("activity", "Fun day"),
    ]
    only = a.get(f"{ORGS}{club.id}/schedule/", {"kind": "activity"}).json()
    assert [i["title"] for i in only] == ["Practice", "Fun day"]
    assert a.get(f"{ORGS}{club.id}/schedule/", {"when": "past"}).json() == []
    calendar = a.get(f"{ORGS}{club.id}/schedule.ics")
    assert calendar["Content-Type"].startswith("text/calendar")
    body = calendar.content.decode()
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.count("BEGIN:VEVENT") == 4
    assert "SUMMARY:Fun day" in body and "Still a draft" not in body
    outsider = logged_in(make_user("e@example.com"))
    assert outsider.get(f"{ORGS}{club.id}/schedule/").status_code == 403
    assert outsider.get(f"{ORGS}{club.id}/schedule.ics").status_code == 403


def test_the_audience_alone_hears_of_publish_changes_and_cancellation(officer, club, members):
    from notifications.models import Notification

    picked = create(officer, club, audience="selected", invitee_ids=[str(members["A"].id)])
    assert not Notification.objects.exists()  # a draft tells nobody
    officer.post(url(club, picked, "publish/"), {}, format="json")
    officer.patch(url(club, picked), {"description": "Bring a jacket"}, format="json")  # not news
    officer.patch(url(club, picked), {"place": "Fort Jesus gate"}, format="json")
    officer.patch(url(club, picked), {"place": "Fort Jesus gate"}, format="json")  # same again
    officer.post(url(club, picked, "cancel/"), {"reason": "Rain"}, format="json")
    got = Notification.objects.filter(recipient=members["A"]).order_by("created_at")
    assert [n.title for n in got] == ["New: Night out", "Changed: Night out", "Cancelled: Night out"]
    assert [n.superseded for n in got] == [True, True, False]
    assert got.last().body == "Rain"
    assert not Notification.objects.exclude(recipient=members["A"]).exists()
    # All-member activities reach every active member.
    everyone = create(officer, club, title="Fun day")
    officer.post(url(club, everyone, "publish/"), {}, format="json")
    assert Notification.objects.filter(title="New: Fun day").count() == 6  # A-D, the officer, the admin
