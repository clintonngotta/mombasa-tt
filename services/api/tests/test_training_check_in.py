"""Training rules and location check-in (REQ-052, TASK-125): the club's rules, checking in only inside
the window and the radius with an accurate enough position, nothing of the position kept, staff marking by
hand, and a session moved to another place."""

from datetime import timedelta

import pytest
from django.utils import timezone

from facilities.models import Table, Venue
from notifications.models import Notification
from organizations.models import Role
from training.models import ClubSession, SessionInvitation, TrainingRules

from .helpers import logged_in, make_user
from .test_club_sessions import MINE, invitation_of, invite, schedule, sessions_url
from .test_roles import ORGS, add_member
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db

# The hall, and points measured from it: one degree of latitude is about 111.2 km.
HALL = (-4.043500, 39.668200)


def north(metres: float) -> dict:
    return {"latitude": HALL[0] + metres / 111_195, "longitude": HALL[1]}


def rules_url(club):
    return f"{ORGS}{club.id}/training-rules/"


def check_in(client, invitation, metres=10, accuracy=20, **extra):
    body = {**north(metres), "accuracy_m": accuracy, **extra}
    return client.post(f"{MINE}{invitation.id}/check-in/", body, format="json")


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    Venue.objects.filter(pk=venue["id"]).update(latitude=HALL[0], longitude=HALL[1])
    add_table(staff, club, venue, "Table 1")
    return venue


@pytest.fixture
def world(staff, club, hall):
    """A session starting in a day with two members invited, a coach who runs training, and an outsider."""
    coach = make_user("coach@example.com", display_name="Coach")
    add_member(
        club, coach, Role.objects.create(organization=club, name="Coach", permissions=["training.manage"])
    )
    ann, ben, outsider = (
        make_user(f"{n}@example.com", display_name=n.title()) for n in ("ann", "ben", "outsider")
    )
    add_member(club, ann)
    add_member(club, ben)
    session = schedule(staff, club, list(Table.objects.filter(venue_id=hall["id"])))
    invite(staff, club, session, ann, ben)
    return {
        "club": club,
        "staff": staff,
        "hall": hall,
        "session": session,
        "coach": logged_in(coach),
        "ann": logged_in(ann),
        "ben": logged_in(ben),
        "outsider": logged_in(outsider),
        "users": {"ann": ann, "ben": ben, "outsider": outsider},
    }


def starting(session, minutes_from_now: int):
    """Move the session so it starts that many minutes from now (negative: it started that long ago)."""
    starts = timezone.now() + timedelta(minutes=minutes_from_now)
    ClubSession.objects.filter(pk=session["id"]).update(starts_at=starts, ends_at=starts + timedelta(hours=2))


def test_training_staff_set_the_rules_and_members_read_them(world):
    club = world["club"]
    defaults = world["ann"].get(rules_url(club)).json()
    assert (defaults["radius_m"], defaults["opens_before_minutes"], defaults["late_after_minutes"]) == (
        300,
        30,
        10,
    )
    assert defaults["can_edit"] is False and defaults["has_location"] is False

    body = {
        "slots": [{"weekday": "tuesday", "starts": "18:00", "ends": "20:00", "title": "Squad"}],
        "venue_id": world["hall"]["id"],
        "radius_m": 150,
        "opens_before_minutes": 20,
        "closes_after_minutes": 45,
        "late_after_minutes": 5,
    }
    assert world["ann"].put(rules_url(club), body, format="json").status_code == 403
    assert world["outsider"].get(rules_url(club)).status_code == 403
    saved = world["coach"].put(rules_url(club), body, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["venue"]["name"] and saved.json()["has_location"] is True
    seen = world["ann"].get(rules_url(club)).json()
    assert seen["slots"] == body["slots"] and seen["radius_m"] == 150

    # A map point instead of a venue: staff see the coordinates, members only its name.
    point = {"venue_id": None, "latitude": HALL[0], "longitude": HALL[1], "location_label": "School hall"}
    assert world["coach"].put(rules_url(club), point, format="json").json()["latitude"] is not None
    seen = world["ann"].get(rules_url(club)).json()
    assert (seen["latitude"], seen["longitude"], seen["location_label"]) == (None, None, "School hall")

    for bad in (
        {"radius_m": 301},  # never wider than 300 m
        {"radius_m": 10},
        {"latitude": 1.0, "longitude": None},
        {"late_after_minutes": 60, "closes_after_minutes": 30},
        {"slots": [{"weekday": "funday", "starts": "18:00", "ends": "20:00"}]},
        {"slots": [{"weekday": "monday", "starts": "20:00", "ends": "18:00"}]},
        {"venue_id": "00000000-0000-4000-8000-000000000000"},
        {"owner": "x"},
    ):
        assert world["coach"].put(rules_url(club), bad, format="json").status_code == 400, bad
    assert TrainingRules.objects.get().radius_m == 150


def test_check_in_only_inside_the_window(world):
    invitation = invitation_of(world["users"]["ann"], world["session"])
    seen = world["ann"].get(MINE).json()["results"][0]["check_in"]
    assert seen["radius_m"] == 300 and seen["place"] == {"label": world["hall"]["name"], "moved": False}
    assert check_in(world["ann"], invitation).json()["code"] == "check_in_not_open"  # a day early
    starting(world["session"], 31)
    assert check_in(world["ann"], invitation).json()["code"] == "check_in_not_open"
    starting(world["session"], -31)
    assert check_in(world["ann"], invitation).json()["code"] == "check_in_closed"
    assert SessionInvitation.objects.get(pk=invitation.pk).attended is None

    # On time, then late: the second member arrives after the late mark.
    starting(world["session"], 20)
    done = check_in(world["ann"], invitation)
    assert done.status_code == 200, done.json()
    assert (done.json()["attended"], done.json()["late"], done.json()["attendance_source"]) == (
        True,
        False,
        "self",
    )
    starting(world["session"], -15)
    late = check_in(world["ben"], invitation_of(world["users"]["ben"], world["session"]))
    assert (late.json()["attended"], late.json()["late"]) == (True, True)


def test_check_in_only_within_range_with_an_accurate_position(world):
    ann = invitation_of(world["users"]["ann"], world["session"])
    starting(world["session"], 5)
    far = check_in(world["ann"], ann, metres=320)
    assert far.status_code == 409 and far.json()["code"] == "too_far"
    vague = check_in(world["ann"], ann, metres=10, accuracy=450)
    assert vague.status_code == 409 and vague.json()["code"] == "position_inaccurate"
    assert "outdoors" in vague.json()["message"]
    for bad in ({"latitude": 91}, {"accuracy_m": -1}, {"note": "x"}):
        assert check_in(world["ann"], ann, **bad).status_code == 400, bad
    missing = world["ann"].post(f"{MINE}{ann.id}/check-in/", {}, format="json")
    assert missing.status_code == 400
    assert SessionInvitation.objects.get(pk=ann.pk).attended is None

    # Within 300 m: accepted. Only the distance, the accuracy and the time are kept.
    near = check_in(world["ann"], ann, metres=280, accuracy=25)
    assert near.status_code == 200, near.json()
    stored = SessionInvitation.objects.get(pk=ann.pk)
    assert 270 <= stored.check_in_distance_m <= 290 and stored.check_in_accuracy_m == 25
    assert stored.attendance_by is None and stored.attendance_at is not None
    kept = {f.name for f in SessionInvitation._meta.get_fields()}
    assert not {name for name in kept if "latitude" in name or "longitude" in name}
    assert "latitude" not in str(near.json()) and "longitude" not in str(near.json())
    # Checking in again changes nothing.
    again = check_in(world["ann"], ann, metres=5)
    assert again.status_code == 200
    assert SessionInvitation.objects.get(pk=ann.pk).check_in_distance_m == stored.check_in_distance_m

    # The club may set a smaller radius.
    world["coach"].put(rules_url(world["club"]), {"radius_m": 100}, format="json")
    ben = invitation_of(world["users"]["ben"], world["session"])
    assert check_in(world["ben"], ben, metres=150).json()["code"] == "too_far"
    assert check_in(world["ben"], ben, metres=60, accuracy=120).json()["code"] == "position_inaccurate"
    assert check_in(world["ben"], ben, metres=60).status_code == 200


def test_only_the_member_checks_themselves_in(world):
    ann = invitation_of(world["users"]["ann"], world["session"])
    starting(world["session"], 5)
    for other in ("ben", "outsider", "coach"):
        assert check_in(world[other], ann).status_code == 404
    # A member who declined, or a cancelled session, can't be checked in to.
    world["ben"].post(
        f"{MINE}{invitation_of(world['users']['ben'], world['session']).id}/decline/", {}, format="json"
    )
    ben = invitation_of(world["users"]["ben"], world["session"])
    assert check_in(world["ben"], ben).json()["code"] == "declined"
    world["staff"].post(sessions_url(world["club"], world["session"], "cancel/"), {}, format="json")
    assert check_in(world["ann"], ann).json()["code"] == "session_cancelled"


def test_staff_still_mark_by_hand_and_the_record_says_so(world):
    club, session = world["club"], world["session"]
    ann = invitation_of(world["users"]["ann"], session)
    ben = invitation_of(world["users"]["ben"], session)
    starting(session, -5)
    check_in(world["ann"], ann, metres=40)
    marked = world["coach"].patch(
        sessions_url(club, session, f"invitations/{ben.id}/"), {"attended": True, "late": True}, format="json"
    )
    assert marked.status_code == 200, marked.json()
    rows = {
        r["display_name"]: r for r in world["coach"].get(sessions_url(club, session, "invitations/")).json()
    }
    assert (rows["Ann"]["attendance_source"], rows["Ann"]["late"]) == ("self", False)
    assert 30 <= rows["Ann"]["check_in_distance_m"] <= 50
    assert (rows["Ben"]["attendance_source"], rows["Ben"]["late"]) == ("staff", True)
    assert rows["Ben"]["check_in_distance_m"] is None
    # Ben sees that staff marked him.
    mine = world["ben"].get(MINE).json()["results"][0]
    assert (mine["attended"], mine["late"], mine["attendance_source"]) == (True, True, "staff")
    # Clearing a mark clears how it was made.
    cleared = world["coach"].patch(
        sessions_url(club, session, f"invitations/{ben.id}/"), {"attended": None}, format="json"
    )
    assert (cleared.json()["attended"], cleared.json()["attendance_source"], cleared.json()["late"]) == (
        None,
        "",
        False,
    )


def test_a_moved_session_is_checked_in_to_at_its_new_place(world):
    club, session, staff = world["club"], world["session"], world["staff"]
    ann = invitation_of(world["users"]["ann"], session)
    location = sessions_url(club, session, "location/")
    moved_to = {"latitude": HALL[0] + 2000 / 111_195, "longitude": HALL[1], "label": "Beach courts"}
    assert world["ann"].post(location, moved_to, format="json").status_code == 403
    for bad in (
        {},
        {"latitude": 1.0},
        {"usual": True, "venue_id": world["hall"]["id"]},
        {"venue_id": str(club.id)},
    ):
        assert world["coach"].post(location, bad, format="json").status_code == 400, bad
    moved = world["coach"].post(location, moved_to, format="json")
    assert moved.status_code == 200, moved.json()
    assert moved.json()["check_in"]["place"] == {"label": "Beach courts", "moved": True}
    # Everyone invited is told, with the place and not its coordinates.
    told = Notification.objects.filter(title="Moved: Tuesday squad")
    assert sorted(told.values_list("recipient__display_name", flat=True)) == ["Ann", "Ben"]
    assert told.first().body == "Now at Beach courts."
    assert world["ann"].get(MINE).json()["results"][0]["check_in"]["place"]["moved"] is True

    # Check-in is measured from the new place: the hall is now 2 km away.
    starting(session, 5)
    assert check_in(world["ann"], ann, metres=10).json()["code"] == "too_far"
    assert check_in(world["ann"], ann, metres=2010).status_code == 200

    # Back to the usual place: told again, and measured from the hall.
    back = staff.post(location, {"usual": True}, format="json")
    assert back.json()["check_in"]["place"]["moved"] is False
    ben = invitation_of(world["users"]["ben"], session)
    assert check_in(world["ben"], ben, metres=2010).json()["code"] == "too_far"
    assert check_in(world["ben"], ben, metres=10).status_code == 200


def test_without_a_known_place_staff_mark_by_hand(world):
    Venue.objects.filter(pk=world["hall"]["id"]).update(latitude=None, longitude=None)
    ann = invitation_of(world["users"]["ann"], world["session"])
    starting(world["session"], 5)
    assert world["ann"].get(MINE).json()["results"][0]["check_in"]["place"] is None
    assert check_in(world["ann"], ann).json()["code"] == "no_location"
