"""Coaching (REQ-047, EVAL-047): coach profiles, coachings, bookings, plans given to trainees and coach's
notes on matches that only the trainee reads."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from coaching.models import Booking, CoachRating, MatchComment

from .helpers import logged_in, make_official, make_user
from .test_reservations import started
from .test_roles import add_member, create_club
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db
ME = "/api/v1/me/"
NAIROBI = ZoneInfo("Africa/Nairobi")


def day_ahead(days=2):
    return (timezone.now().astimezone(NAIROBI) + timedelta(days=days)).date()


def at(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time(), NAIROBI).replace(hour=hour, minute=minute)


def become_coach(client, **profile):
    body = {
        "headline": "Footwork and serve coach",
        "levels": ["beginner"],
        "specialties": ["serve"],
        **profile,
    }
    response = client.put(f"{ME}coach-profile/", body, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def open_week(client, venue="Makadara hall"):
    windows = [{"weekday": d, "starts": "08:00", "ends": "18:00", "venue": venue} for d in range(7)]
    response = client.put(f"{ME}coach-availability/", {"windows": windows}, format="json")
    assert response.status_code == 200, response.json()


def coaching_between(coach_client, trainee_client, coach):
    asked = trainee_client.post(
        f"{ME}coachings/", {"coach_id": str(coach.id), "message": "Help my serve"}, format="json"
    )
    assert asked.status_code == 201, asked.json()
    coaching = asked.json()
    assert coaching["role"] == "trainee" and not coaching["awaiting_me"]
    accepted = coach_client.post(f"{ME}coachings/{coaching['id']}/accept/", format="json")
    assert accepted.status_code == 200 and accepted.json()["status"] == "active"
    return coaching["id"]


@pytest.fixture
def people():
    coach = make_user("coach@example.com", display_name="Coach Amina")
    trainee = make_user("trainee@example.com", display_name="Trainee Baraka")
    coach_client, trainee_client = logged_in(coach), logged_in(trainee)
    become_coach(coach_client)
    open_week(coach_client)
    return coach, trainee, coach_client, trainee_client


def test_coaches_are_listed_while_taking_players(people):
    coach, _, coach_client, trainee_client = people
    listed = trainee_client.get("/api/v1/coaches/", {"skill": "serve"}).json()["results"]
    assert [c["user"]["id"] for c in listed] == [str(coach.id)]
    assert listed[0]["availability"][0]["venue"] == "Makadara hall"
    assert set(listed[0]) >= {"headline", "levels", "specialties", "rate_minor", "accepting"}
    assert trainee_client.get("/api/v1/coaches/", {"skill": "footwork"}).json()["results"] == []

    become_coach(coach_client, accepting=False)
    assert trainee_client.get("/api/v1/coaches/").json()["results"] == []
    assert trainee_client.get(f"/api/v1/coaches/{coach.id}/").status_code == 404
    assert (
        trainee_client.post(f"{ME}coachings/", {"coach_id": str(coach.id)}, format="json").status_code == 400
    )


def test_a_coach_profile_names_only_clubs_the_coach_belongs_to(people):
    coach, _, coach_client, _ = people
    club = create_club(make_user("owner@example.com"), name="Coast Spinners")
    other = create_club(make_user("other@example.com"), name="Other TT")
    add_member(club, coach)
    bad = coach_client.put(f"{ME}coach-profile/", {"organization_ids": [str(other.id)]}, format="json")
    assert bad.status_code == 400
    good = coach_client.put(f"{ME}coach-profile/", {"organization_ids": [str(club.id)]}, format="json").json()
    assert [o["name"] for o in good["organizations"]] == ["Coast Spinners"]


def test_coaching_is_asked_accepted_and_ended(people):
    coach, trainee, coach_client, trainee_client = people
    coaching_id = coaching_between(coach_client, trainee_client, coach)
    again = trainee_client.post(f"{ME}coachings/", {"coach_id": str(coach.id)}, format="json")
    assert again.status_code == 409
    assert coach_client.get(f"{ME}trainees/{coaching_id}/").status_code == 200
    # A trainee can't open the coach's view of themselves.
    assert trainee_client.get(f"{ME}trainees/{coaching_id}/").status_code == 404

    assert trainee_client.post(f"{ME}coachings/{coaching_id}/end/", format="json").json()["status"] == "ended"
    assert coach_client.get(f"{ME}trainees/{coaching_id}/").status_code == 404
    # Asking again after it ended is a new request.
    assert (
        trainee_client.post(f"{ME}coachings/", {"coach_id": str(coach.id)}, format="json").status_code == 201
    )


def test_only_the_other_side_answers_a_request(people):
    coach, trainee, coach_client, trainee_client = people
    invited = coach_client.post(f"{ME}coachings/", {"trainee_id": str(trainee.id)}, format="json").json()
    assert invited["role"] == "coach"
    assert coach_client.post(f"{ME}coachings/{invited['id']}/accept/", format="json").status_code == 409
    stranger = logged_in(make_user("stranger@example.com"))
    assert stranger.post(f"{ME}coachings/{invited['id']}/accept/", format="json").status_code == 404
    assert trainee_client.get(f"{ME}coachings/").json()[0]["awaiting_me"] is True
    assert (
        trainee_client.post(f"{ME}coachings/{invited['id']}/decline/", format="json").json()["status"]
        == "declined"
    )
    # A player without a coach profile can't invite anyone.
    assert (
        trainee_client.post(f"{ME}coachings/", {"trainee_id": str(coach.id)}, format="json").status_code
        == 404
    )


def test_bookings_fit_the_coach_availability_and_both_calendars(people):
    coach, trainee, coach_client, trainee_client = people
    day = day_ahead()
    slots = trainee_client.get(
        f"/api/v1/coaches/{coach.id}/slots/", {"from": day.isoformat(), "days": 1}
    ).json()
    assert (
        slots[0]["starts_at"].startswith(f"{day.isoformat()}T08:00") and slots[0]["venue"] == "Makadara hall"
    )

    def book(client, start, end, expect=201):
        body = {"coach_id": str(coach.id), "starts_at": start.isoformat(), "ends_at": end.isoformat()}
        response = client.post(f"{ME}bookings/", body, format="json")
        assert response.status_code == expect, response.json()
        return response.json()

    book(trainee_client, at(day, 19), at(day, 20), expect=400)  # after the coach's hours
    book(trainee_client, at(day, 10), at(day, 10, 15), expect=400)  # too short
    booking = book(trainee_client, at(day, 10), at(day, 11))
    assert booking["status"] == "requested" and booking["role"] == "trainee"

    # A requested booking already holds the coach's time, for anybody else.
    other = logged_in(make_user("other@example.com"))
    clash = book(other, at(day, 10, 30), at(day, 11, 30), expect=409)
    assert clash["code"] == "calendar_conflict"
    taken = trainee_client.get(
        f"/api/v1/coaches/{coach.id}/slots/", {"from": day.isoformat(), "days": 1}
    ).json()
    assert not any(s["starts_at"].startswith(f"{day.isoformat()}T10:00") for s in taken)

    # The trainee can't confirm their own booking; the coach does.
    assert trainee_client.post(f"{ME}bookings/{booking['id']}/confirm/", format="json").status_code == 404
    confirmed = coach_client.post(f"{ME}bookings/{booking['id']}/confirm/", format="json").json()
    assert confirmed["status"] == "confirmed" and confirmed["role"] == "coach"

    # It's in the coach's calendar and blocks a training session in the trainee's own plan.
    calendar = coach_client.get(
        f"{ME}coach-calendar/", {"from": day.isoformat(), "to": day.isoformat()}
    ).json()
    assert [(e["kind"], e["status"]) for e in calendar] == [("booking", "confirmed")]
    plan = trainee_client.post(f"{ME}training-plans/", {"title": "Serve week"}, format="json").json()
    session = {
        "kind": "session",
        "title": "Serve",
        "starts_at": at(day, 10, 30).isoformat(),
        "ends_at": at(day, 12).isoformat(),
    }
    assert (
        trainee_client.post(f"{ME}training-plans/{plan['id']}/items/", session, format="json").status_code
        == 409
    )

    cancelled = trainee_client.post(
        f"{ME}bookings/{booking['id']}/cancel/", {"reason": "Sick"}, format="json"
    ).json()
    assert cancelled["status"] == "cancelled" and cancelled["reason"] == "Sick"
    book(other, at(day, 10, 30), at(day, 11, 30))


def test_a_coach_gives_a_trainee_a_plan_and_sees_their_progress(people):
    coach, trainee, coach_client, trainee_client = people
    coaching_id = coaching_between(coach_client, trainee_client, coach)
    source = coach_client.post(
        f"{ME}training-plans/", {"title": "Serve block", "goal_skills": ["serve"]}, format="json"
    ).json()
    coach_client.post(
        f"{ME}training-plans/{source['id']}/items/",
        {"kind": "checklist", "title": "50 short serves"},
        format="json",
    )

    given = coach_client.post(
        f"{ME}trainees/{coaching_id}/plans/", {"source_plan_id": source["id"]}, format="json"
    )
    assert given.status_code == 201, given.json()
    plan = given.json()
    assert plan["coach_name"] == "Coach Amina" and plan["progress"] == {"done": 0, "total": 1}

    # The trainee owns it and ticks it off; the coach sees that progress, not their own copy's.
    mine = trainee_client.get(f"{ME}training-plans/{plan['id']}/").json()
    item = mine["items"][0]
    trainee_client.patch(
        f"{ME}training-plans/{plan['id']}/items/{item['id']}/", {"completed": True}, format="json"
    )
    seen = coach_client.get(f"{ME}trainees/{coaching_id}/").json()
    assert [(p["title"], p["progress"]) for p in seen["plans"]] == [("Serve block", {"done": 1, "total": 1})]
    assert coach_client.get(f"{ME}training-plans/{source['id']}/").json()["progress"]["done"] == 0

    # The coach adds to it while they coach; afterwards they can't, and the trainee keeps it.
    path = f"{ME}trainees/{coaching_id}/plans/{plan['id']}/items/"
    assert (
        coach_client.post(path, {"kind": "checklist", "title": "Shadow footwork"}, format="json").status_code
        == 201
    )
    coach_client.post(f"{ME}coachings/{coaching_id}/end/", format="json")
    assert coach_client.post(path, {"kind": "checklist", "title": "More"}, format="json").status_code == 404
    assert trainee_client.get(f"{ME}training-plans/{plan['id']}/").json()["progress"]["total"] == 2


def test_a_trainee_opens_the_coachs_own_drill_from_their_plan_and_nobody_else_does(people, staff):
    coach, trainee, coach_client, trainee_client = people
    coaching_id = coaching_between(coach_client, trainee_client, coach)
    drill = lambda title: coach_client.post(  # noqa: E731
        f"{ME}drills/", {"title": title, "instructions": "Ten short serves."}, format="json"
    ).json()
    listed, in_session, unused = drill("Serve ladder"), drill("Receive ladder"), drill("Not given")
    plan = coach_client.post(f"{ME}trainees/{coaching_id}/plans/", {"title": "Serves"}, format="json").json()
    items = f"{ME}trainees/{coaching_id}/plans/{plan['id']}/items/"
    assert (
        coach_client.post(items, {"kind": "checklist", "drill": listed["id"]}, format="json").status_code
        == 201
    )
    start = at(day_ahead(3), 18, 0)
    session = coach_client.post(
        items,
        {
            "kind": "session",
            "title": "Session",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "activities": [
                {"phase": "on_table", "title": "Receive", "minutes": 10, "drill": in_session["id"]}
            ],
        },
        format="json",
    )
    assert session.status_code == 201, session.json()

    # The trainee reads both drills, labelled as the coach's, and can't change them.
    for given in (listed, in_session):
        seen = trainee_client.get(f"/api/v1/drills/{given['id']}/")
        assert seen.status_code == 200 and seen.json()["library"] == "coach"
        assert (
            trainee_client.patch(f"{ME}drills/{given['id']}/", {"title": "x"}, format="json").status_code
            == 404
        )
    assert coach_client.get(f"/api/v1/drills/{listed['id']}/").json()["library"] == "personal"
    # Not the coach's other drills, not in the trainee's library, and nobody else reads any of them.
    assert trainee_client.get(f"/api/v1/drills/{unused['id']}/").status_code == 404
    assert listed["id"] not in [d["id"] for d in trainee_client.get("/api/v1/drills/").json()]
    assert staff.get(f"/api/v1/drills/{listed['id']}/").status_code == 404


def test_players_who_trained_with_a_coach_rate_them_and_the_profile_shows_the_average(people, staff):
    coach, trainee, coach_client, trainee_client = people
    rating = f"/api/v1/coaches/{coach.id}/rating/"
    page = f"/api/v1/coaches/{coach.id}/"

    # Before training with the coach nobody rates them, and nobody rates themselves.
    seen = trainee_client.get(page).json()
    assert (seen["rating_average"], seen["rating_count"], seen["my_rating"], seen["can_rate"]) == (
        None,
        0,
        None,
        False,
    )
    refused = trainee_client.put(rating, {"stars": 5}, format="json")
    assert refused.status_code == 403 and refused.json()["code"] == "cannot_rate"
    assert coach_client.put(rating, {"stars": 5}, format="json").status_code == 403

    coaching_id = coaching_between(coach_client, trainee_client, coach)
    assert trainee_client.get(page).json()["can_rate"] is True
    for bad in (0, 6, "five"):
        assert trainee_client.put(rating, {"stars": bad}, format="json").status_code == 400
    rated = trainee_client.put(rating, {"stars": 4}, format="json")
    assert rated.status_code == 200, rated.json()
    assert (rated.json()["rating_average"], rated.json()["rating_count"], rated.json()["my_rating"]) == (
        4.0,
        1,
        4,
    )

    # Rating again changes their one rating; it survives the coaching ending.
    trainee_client.put(rating, {"stars": 5}, format="json")
    coach_client.post(f"{ME}coachings/{coaching_id}/end/", format="json")
    assert trainee_client.put(rating, {"stars": 3}, format="json").status_code == 200
    assert CoachRating.objects.count() == 1

    # Everyone sees the average and the count; only the rater sees their own rating.
    for client in (staff, coach_client):
        other = client.get(page).json()
        assert (other["rating_average"], other["rating_count"], other["my_rating"], other["can_rate"]) == (
            3.0,
            1,
            None,
            False,
        )
    listed = staff.get("/api/v1/coaches/").json()["results"]
    assert [(c["rating_average"], c["rating_count"]) for c in listed if c["user"]["id"] == str(coach.id)] == [
        (3.0, 1)
    ]
    assert coach_client.get(f"{ME}coach-profile/").json()["rating_average"] == 3.0
    assert staff.put(rating, {"stars": 1}, format="json").status_code == 403

    gone = trainee_client.delete(rating)
    assert gone.status_code == 200 and gone.json()["rating_count"] == 0 and gone.json()["my_rating"] is None


def test_a_coachs_plan_session_shares_the_hour_of_their_booked_session(people):
    coach, trainee, coach_client, trainee_client = people
    coaching_id = coaching_between(coach_client, trainee_client, coach)
    day = day_ahead()

    def book(start, end):
        body = {"coach_id": str(coach.id), "starts_at": start.isoformat(), "ends_at": end.isoformat()}
        return trainee_client.post(f"{ME}bookings/", body, format="json")

    def session(start, end):
        return {
            "kind": "session",
            "title": "Serves",
            "starts_at": start.isoformat(),
            "ends_at": end.isoformat(),
        }

    assert book(at(day, 10), at(day, 11)).status_code == 201
    plan = coach_client.post(f"{ME}trainees/{coaching_id}/plans/", {"title": "Serves"}, format="json").json()
    items = f"{ME}trainees/{coaching_id}/plans/{plan['id']}/items/"
    # The coach lays out the booked hour: the plan session is that booking's running order.
    assert coach_client.post(items, session(at(day, 10), at(day, 11)), format="json").status_code == 201
    # And the other way round: a session the coach planned can then be booked with them.
    assert coach_client.post(items, session(at(day, 14), at(day, 15)), format="json").status_code == 201
    assert book(at(day, 14), at(day, 15)).status_code == 201
    # The trainee's own plan is still blocked by the booking.
    own = trainee_client.post(f"{ME}training-plans/", {"title": "Mine"}, format="json").json()
    clash = trainee_client.post(
        f"{ME}training-plans/{own['id']}/items/", session(at(day, 10), at(day, 11)), format="json"
    )
    assert clash.status_code == 409 and clash.json()["code"] == "calendar_conflict"


def test_the_coach_marks_a_held_session_done(people):
    coach, trainee, coach_client, trainee_client = people
    day = day_ahead()
    body = {
        "coach_id": str(coach.id),
        "starts_at": at(day, 10).isoformat(),
        "ends_at": at(day, 11).isoformat(),
    }
    booking = trainee_client.post(f"{ME}bookings/", body, format="json").json()
    done = f"{ME}bookings/{booking['id']}/complete/"

    # Not before the coach confirmed it, and not before it starts.
    assert coach_client.post(done, format="json").json()["code"] == "not_confirmed"
    coach_client.post(f"{ME}bookings/{booking['id']}/confirm/", format="json")
    assert coach_client.post(done, format="json").json()["code"] == "not_started"
    Booking.objects.filter(pk=booking["id"]).update(
        starts_at=timezone.now() - timedelta(hours=2), ends_at=timezone.now() - timedelta(hours=1)
    )
    # Only the coach marks it; the trainee and a stranger get 404.
    assert trainee_client.post(done, format="json").status_code == 404
    assert logged_in(make_user("stranger@example.com")).post(done, format="json").status_code == 404
    held = coach_client.post(done, format="json")
    assert held.status_code == 200 and held.json()["status"] == "completed"
    assert coach_client.post(done, format="json").status_code == 409

    # Both sides see it as done among their past sessions, and the trainee may now rate the coach.
    for client in (coach_client, trainee_client):
        assert [b["status"] for b in client.get(f"{ME}bookings/", {"past": "1"}).json()] == ["completed"]
    assert trainee_client.get(f"/api/v1/coaches/{coach.id}/").json()["can_rate"] is True


def test_coach_notes_are_read_by_the_trainee_alone(people, staff, club):
    coach, trainee, coach_client, trainee_client = people
    coaching_id = coaching_between(coach_client, trainee_client, coach)
    logged = trainee_client.post(
        f"{ME}matches/",
        {
            "played_on": day_ahead(-1).isoformat(),
            "label": "Friendly",
            "opponent_name": "Juma",
            "games": [{"my_points": 11, "opponent_points": 7}],
        },
        format="json",
    ).json()
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    game = started(staff, club, venue, [["Trainee Baraka"], ["Rival Chao"]])

    seen = coach_client.get(f"{ME}trainees/{coaching_id}/").json()
    assert {(m["kind"], str(m["id"])) for m in seen["matches"]} == {
        ("personal", logged["id"]),
        ("official", str(game["match"].id)),
    }

    path = f"{ME}trainees/{coaching_id}/comments/"
    note = coach_client.post(
        path, {"personal_match": logged["id"], "body": "Great first serve."}, format="json"
    )
    assert note.status_code == 201, note.json()
    official = coach_client.post(
        path, {"match": str(game["match"].id), "body": "Watch his backhand."}, format="json"
    )
    assert official.status_code == 201, official.json()
    # The coach's page for the trainee still loads, with each note under its match.
    again = coach_client.get(f"{ME}trainees/{coaching_id}/")
    assert again.status_code == 200, again.content
    assert sorted(c["body"] for m in again.json()["matches"] for c in m["comments"]) == [
        "Great first serve.",
        "Watch his backhand.",
    ]
    # Someone else's match can't be commented on.
    rival_log = (
        logged_in(make_user("rival2@example.com"))
        .post(
            f"{ME}matches/",
            {
                "played_on": day_ahead(-1).isoformat(),
                "label": "Friendly",
                "games": [{"my_points": 11, "opponent_points": 3}],
            },
            format="json",
        )
        .json()
    )
    assert (
        coach_client.post(path, {"personal_match": rival_log["id"], "body": "x"}, format="json").status_code
        == 404
    )

    notes = trainee_client.get(f"{ME}coach-notes/", {"personal_match": logged["id"]}).json()
    assert [n["body"] for n in notes] == ["Great first serve."]
    assert set(notes[0]) == {"id", "coach", "personal_match", "match", "body", "created_at", "updated_at"}

    # Nobody else reads them: not the club's staff, not an official, not another player.
    official_user = make_user("official@example.com")
    make_official(official_user, "KE")
    for outsider in (staff, logged_in(official_user), logged_in(make_user("nosy@example.com"))):
        assert outsider.get(f"{ME}coach-notes/").json() == []
        assert outsider.get(f"{ME}trainees/{coaching_id}/").status_code == 404
        assert outsider.delete(f"{ME}coach-comments/{note.json()['id']}/").status_code == 404

    # When the coaching ends the coach loses them; the trainee keeps them.
    coach_client.post(f"{ME}coachings/{coaching_id}/end/", format="json")
    assert (
        coach_client.patch(
            f"{ME}coach-comments/{note.json()['id']}/", {"body": "x"}, format="json"
        ).status_code
        == 404
    )
    assert len(trainee_client.get(f"{ME}coach-notes/").json()) == 2
    assert MatchComment.objects.count() == 2
