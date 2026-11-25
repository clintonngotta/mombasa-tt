"""Events that are not competitions, for people beyond the membership (REQ-046, TASK-110): a body's
representatives, named people, or every signed-in player; check-in and attendance."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from activities.models import Activity, Rsvp
from notifications.models import Notification
from organizations.models import Representative
from profiles.models import PlayerProfile

from .helpers import logged_in, make_user
from .test_activities import create, rsvp, url
from .test_representatives import make_body
from .test_roles import add_member, create_club

pytestmark = pytest.mark.django_db

EVENTS = "/api/v1/me/events/"


def person(name, *, listed=False):
    user = make_user(f"{name.lower()}@example.com", display_name=name)
    if listed:
        PlayerProfile.objects.update_or_create(user=user, defaults={"directory_opt_in": True})
    return user


def publish(client, club, activity):
    out = client.post(url(club, activity, "publish/"), {}, format="json")
    assert out.status_code == 200, out.json()
    return out.json()


def running(activity):
    now = timezone.now()
    Activity.objects.filter(pk=activity["id"]).update(
        starts_at=now - timedelta(minutes=10), ends_at=now + timedelta(hours=1)
    )


def my_events(client) -> list[str]:
    return [event["title"] for event in client.get(EVENTS).json()]


@pytest.fixture
def world():
    """Two clubs of the Mombasa region, its body, a seated representative of each club, a lapsed one, a
    listed player and an unlisted one."""
    coast_admin, nyali_admin, chair = person("CoastAdmin"), person("NyaliAdmin"), person("Chair")
    coast, nyali = create_club(coast_admin), create_club(nyali_admin, name="Nyali TT")
    for club in (coast, nyali):
        club.country, club.region = "KE", "Mombasa"
        club.save(update_fields=["country", "region"])
    body = make_body("Mombasa Region TT", chair)
    people = {
        name: person(name, listed=name == "Listed")
        for name in ("CoastRep", "NyaliRep", "Lapsed", "Listed", "Unlisted", "Member")
    }
    add_member(coast, people["Member"])
    seat = {"body": body, "status": Representative.Status.ACCEPTED}
    Representative.objects.create(user=people["CoastRep"], sender=coast, **seat)
    Representative.objects.create(user=people["NyaliRep"], sender=nyali, **seat)
    Representative.objects.create(
        user=people["Lapsed"], sender=coast, term_end=timezone.localdate() - timedelta(days=1), **seat
    )
    made = {
        "coast": coast,
        "nyali": nyali,
        "body": body,
        "desk": logged_in(chair),
        "coast_desk": logged_in(coast_admin),
        "users": people,
        **{name: logged_in(user) for name, user in people.items()},
    }
    cache.clear()  # the logins above used up the login allowance
    return made


def test_a_body_invites_representatives_of_all_or_chosen_clubs(world):
    body, desk = world["body"], world["desk"]
    # Only a body has representatives to invite, and only its own senders can be chosen.
    create(world["coast_desk"], world["coast"], expect=400, audience="reps")
    create(desk, body, expect=400, audience="reps", club_ids=[str(body.id)])
    everyone = publish(desk, body, create(desk, body, title="Clinic", kind="clinic", audience="reps"))
    coast_only = publish(
        desk,
        body,
        create(desk, body, title="Coast briefing", audience="reps", club_ids=[str(world["coast"].id)]),
    )
    assert my_events(world["CoastRep"]) == ["Clinic", "Coast briefing"]
    assert my_events(world["NyaliRep"]) == ["Clinic"]
    for outsider in ("Lapsed", "Member", "Listed"):
        client = world[outsider]
        assert my_events(client) == []
        assert client.get(url(body, everyone)).status_code == 404
        assert (
            client.post(url(body, everyone, "rsvp/"), {"answer": "going"}, format="json").status_code == 404
        )
    assert world["NyaliRep"].get(url(body, coast_only)).status_code == 404
    seen = world["CoastRep"].get(url(body, everyone)).json()
    assert seen["can_answer"] is True and seen["organization"]["name"] == "Mombasa Region TT"
    assert rsvp(world["CoastRep"], body, everyone, "going")["my_answer"] == "going"
    # Those invited are told; nobody else.
    told = Notification.objects.filter(title="New: Clinic").values_list("recipient__display_name", flat=True)
    assert sorted(told) == ["CoastRep", "NyaliRep"]


def test_named_people_are_members_or_listed_players(world):
    coast, desk, users = world["coast"], world["coast_desk"], world["users"]
    refused = create(desk, coast, expect=400, audience="named", invitee_ids=[str(users["Unlisted"].id)])
    assert "invitee_ids" in refused["fields"]
    create(desk, coast, expect=400, audience="named")  # nobody named
    event = publish(
        desk,
        coast,
        create(
            desk,
            coast,
            title="Award night",
            kind="awards",
            audience="named",
            invitee_ids=[str(users["Listed"].id), str(users["Member"].id)],
        ),
    )
    assert my_events(world["Listed"]) == ["Award night"]
    assert world["Listed"].get(url(coast, event)).json()["can_answer"] is True
    assert rsvp(world["Listed"], coast, event, "going")["going"] == 1
    # A member who wasn't named doesn't see it, though they belong to the club.
    other = person("Other")
    add_member(coast, other)
    assert logged_in(other).get(url(coast, event)).status_code == 404
    assert world["Unlisted"].get(url(coast, event)).status_code == 404
    # The audience sees who is going by name.
    names = [row["display_name"] for row in world["Member"].get(url(coast, event, "attendees/")).json()]
    assert names == ["Listed"]


def test_an_open_event_is_for_every_signed_in_player(world):
    coast, desk = world["coast"], world["coast_desk"]
    event = publish(
        desk, coast, create(desk, coast, title="Open day", kind="open_day", audience="open", capacity=1)
    )
    assert my_events(world["Unlisted"]) == ["Open day"]
    assert Notification.objects.filter(title="New: Open day").count() == 0  # nobody is told unasked
    assert rsvp(world["Unlisted"], coast, event, "going")["my_waitlisted"] is False
    assert rsvp(world["Listed"], coast, event, "going")["my_waitlisted"] is True
    # Names of who is going at an open event are for its staff.
    assert world["Listed"].get(url(coast, event, "attendees/")).status_code == 403
    rows = desk.get(url(coast, event, "attendees/")).json()
    assert [(row["display_name"], row["waitlisted"]) for row in rows] == [
        ("Unlisted", False),
        ("Listed", True),
    ]
    # A change reaches those who answered.
    desk.patch(url(coast, event), {"place": "Clubhouse"}, format="json")
    told = Notification.objects.filter(title="Changed: Open day").values_list(
        "recipient__display_name", flat=True
    )
    assert sorted(told) == ["Listed", "Unlisted"]
    assert logged_in(person("Later")).get(url(coast, event)).status_code == 200


def test_a_welfare_visit_or_a_shared_cost_stays_with_members(world):
    coast, desk = world["coast"], world["coast_desk"]
    event = publish(desk, coast, create(desk, coast, title="Open day", audience="open"))
    rsvp(world["Listed"], coast, event, "going")
    shared = desk.post(
        url(coast, event, "cost-share/"),
        {"amount_minor": 50000, "due_on": str(timezone.localdate() + timedelta(days=7))},
        format="json",
    )
    assert shared.status_code == 409 and shared.json()["code"] == "members_only"


def test_check_in_while_it_runs_and_staff_mark_the_rest(world):
    body, desk, users = world["body"], world["desk"], world["users"]
    event = publish(desk, body, create(desk, body, title="Clinic", audience="reps"))
    rsvp(world["NyaliRep"], body, event, "going")
    check_in = url(body, event, "check-in/")
    attendance = url(body, event, "attendance/")
    assert world["CoastRep"].post(check_in, {}, format="json").json()["code"] == "not_in_progress"
    early = desk.post(attendance, {"user_id": str(users["CoastRep"].id), "attended": True}, format="json")
    assert early.json()["code"] == "not_started"
    assert world["CoastRep"].get(url(body, event)).json()["can_check_in"] is False
    running(event)
    assert world["CoastRep"].get(url(body, event)).json()["can_check_in"] is True
    assert world["Lapsed"].post(check_in, {}, format="json").status_code == 404

    # Checking in without having answered takes a place and marks you there.
    checked = world["CoastRep"].post(check_in, {}, format="json")
    assert checked.status_code == 200, checked.json()
    assert checked.json()["my_answer"] == "going" and checked.json()["my_checked_in_at"]
    mine = Rsvp.objects.get(activity_id=event["id"], user=users["CoastRep"])
    assert mine.attended is True and mine.marked_by is None

    # Staff see attendance and mark by hand; the audience sees names and nothing of attendance.
    rows = {row["display_name"]: row for row in desk.get(url(body, event, "attendees/")).json()}
    assert rows["CoastRep"]["attended"] is True and rows["CoastRep"]["checked_in_at"]
    assert rows["NyaliRep"]["attended"] is None
    seen = world["NyaliRep"].get(url(body, event, "attendees/")).json()
    assert all(row["attended"] is None and row["checked_in_at"] is None for row in seen)
    body_of = {"rsvp": rows["NyaliRep"]["id"], "attended": False}
    assert world["NyaliRep"].post(attendance, body_of, format="json").status_code == 403
    assert world["Member"].post(attendance, body_of, format="json").status_code in (403, 404)
    marked = desk.post(attendance, body_of, format="json")
    assert marked.status_code == 200 and marked.json()["attended"] is False
    assert Rsvp.objects.get(pk=rows["NyaliRep"]["id"]).marked_by == world["body"].memberships.get().user
    # Bad requests: both or neither, an unknown field, someone outside the audience.
    assert desk.post(attendance, {"attended": True}, format="json").status_code == 400
    assert desk.post(attendance, {**body_of, "note": "x"}, format="json").status_code == 400
    outsider = {"user_id": str(users["Member"].id), "attended": True}
    assert desk.post(attendance, outsider, format="json").status_code == 404


def test_check_in_respects_capacity_and_open_events_take_no_names_from_staff(world):
    coast, desk, users = world["coast"], world["coast_desk"], world["users"]
    event = publish(desk, coast, create(desk, coast, title="Open day", audience="open", capacity=1))
    rsvp(world["Listed"], coast, event, "going")
    running(event)
    full = world["Unlisted"].post(url(coast, event, "check-in/"), {}, format="json")
    assert full.status_code == 409 and full.json()["code"] == "activity_full"
    assert world["Listed"].post(url(coast, event, "check-in/"), {}, format="json").status_code == 200
    # Staff can't put a name on an open event's list for someone who never answered.
    named = {"user_id": str(users["Unlisted"].id), "attended": True}
    assert desk.post(url(coast, event, "attendance/"), named, format="json").status_code == 404
    assert not Rsvp.objects.filter(activity_id=event["id"], user=users["Unlisted"]).exists()


def test_members_activities_work_as_before_and_can_be_checked_in_to(world):
    coast, desk = world["coast"], world["coast_desk"]
    activity = publish(desk, coast, create(desk, coast, title="Night out"))
    assert my_events(world["Member"]) == []  # the club's own activities are on its schedule
    assert world["Listed"].get(url(coast, activity)).status_code == 404
    running(activity)
    assert world["Member"].post(url(coast, activity, "check-in/"), {}, format="json").status_code == 200
