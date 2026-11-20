"""Equipment, drill libraries and personal training plans (REQ-026, REQ-027; EVAL-026, EVAL-027;
TASK-042, TASK-043)."""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from training.models import PlanItem

from .helpers import logged_in, make_user
from .test_reservations import person, started
from .test_roles import ORGS, add_member, create_club
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db
ME = "/api/v1/me/"


def at(hours: float) -> str:
    """An instant `hours` from a fixed point tomorrow, as the API takes it."""
    base = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return (base + timedelta(hours=hours)).isoformat()


def plan(client, title="Footwork block") -> dict:
    made = client.post(f"{ME}training-plans/", {"title": title}, format="json")
    assert made.status_code == 201, made.json()
    return made.json()


def add_item(client, plan_id, expect=201, **body) -> dict:
    response = client.post(f"{ME}training-plans/{plan_id}/items/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_equipment_is_optional_and_private(db):
    player = make_user("player@example.com")
    client = logged_in(player)
    assert client.get(f"{ME}equipment/").json() == {
        "blade": "",
        "forehand": "",
        "backhand": "",
        "updated_at": None,
    }
    saved = client.put(f"{ME}equipment/", {"blade": "Allround wood"}, format="json").json()
    assert saved["blade"] == "Allround wood" and saved["forehand"] == ""
    # Other players never reach it: it is not part of the player page.
    page = logged_in(make_user("other@example.com")).get(f"/api/v1/players/{player.id}/")
    assert "Allround wood" not in page.content.decode()


def test_personal_drills_belong_to_their_owner(db):
    owner = logged_in(make_user("owner@example.com"))
    assert owner.post(f"{ME}drills/", {"title": "Serve practice"}, format="json").status_code == 400
    drill = owner.post(
        f"{ME}drills/",
        {
            "title": "Serve practice",
            "instructions": "Ten short backspin serves to each corner.",
            "duration_minutes": 15,
        },
        format="json",
    ).json()
    assert drill["library"] == "personal" and drill["duration_minutes"] == 15

    stranger = logged_in(make_user("stranger@example.com"))
    assert stranger.get(f"{ME}drills/").json()["results"] == []
    assert stranger.patch(f"{ME}drills/{drill['id']}/", {"title": "Mine"}, format="json").status_code == 404
    assert owner.patch(f"{ME}drills/{drill['id']}/", {"instructions": ""}, format="json").status_code == 400
    assert (
        owner.patch(f"{ME}drills/{drill['id']}/", {"focus": "Serve"}, format="json").json()["focus"]
        == "Serve"
    )


def test_club_drills_are_read_by_members_and_edited_by_training_staff(admin, club):
    coach, member = make_user("coach@example.com"), make_user("member@example.com")
    add_member(club, coach, "captain")  # captains hold training.manage
    add_member(club, member)
    drills = f"{ORGS}{club.id}/drills/"
    body = {"title": "Falkenberg", "instructions": "Backhand, forehand from the backhand corner, forehand."}

    coaching, client = logged_in(coach), logged_in(member)
    assert client.post(drills, body, format="json").status_code == 403
    made = coaching.post(drills, body, format="json")
    assert made.status_code == 201 and made.json()["library"] == "club"
    drill = made.json()["id"]
    assert [d["title"] for d in client.get(drills).json()] == ["Falkenberg"]
    assert client.patch(f"{drills}{drill}/", {"title": "X"}, format="json").status_code == 403
    assert logged_in(make_user("outsider@example.com")).get(drills).status_code == 403
    changed = coaching.patch(f"{drills}{drill}/", {"repetitions": 20}, format="json")
    assert changed.json()["repetitions"] == 20

    # A member puts the club drill in a plan; deleting it later keeps the item and its title.
    mine = plan(client)
    item = add_item(client, mine["id"], kind="checklist", drill=drill)["items"][0]
    assert item["title"] == "Falkenberg" and item["drill_title"] == "Falkenberg"
    assert coaching.delete(f"{drills}{drill}/").status_code == 204
    kept = client.get(f"{ME}training-plans/{mine['id']}/").json()["items"][0]
    assert kept["title"] == "Falkenberg" and kept["drill"] is None

    # A drill of a club they're not in, or someone else's personal drill, can't go into a plan.
    other_admin = make_user("other-admin@example.com")
    other = create_club(other_admin, "Other club")
    foreign = logged_in(other_admin).post(f"{ORGS}{other.id}/drills/", body, format="json")
    add_item(client, mine["id"], expect=400, kind="checklist", drill=foreign.json()["id"])
    personal = coaching.post(f"{ME}drills/", body, format="json").json()
    add_item(client, mine["id"], expect=400, kind="checklist", drill=personal["id"])


def test_checklists_reserve_nothing_and_sessions_may_not_overlap(db):
    player = make_user("player@example.com")
    client = logged_in(player)
    mine = plan(client)
    add_item(client, mine["id"], kind="checklist", title="Stretch every morning")
    add_item(client, mine["id"], kind="checklist", title="Watch a match video")
    add_item(client, mine["id"], expect=400, kind="checklist", title="Timed", starts_at=at(0), ends_at=at(1))
    add_item(
        client, mine["id"], expect=400, kind="session", title="Backwards", starts_at=at(1), ends_at=at(0)
    )

    first = add_item(client, mine["id"], kind="session", title="Multiball", starts_at=at(0), ends_at=at(1.5))
    # Back to back is fine; overlapping is refused with what it clashes with, in any of the player's plans.
    add_item(client, mine["id"], kind="session", title="Serves", starts_at=at(1.5), ends_at=at(2))
    other = plan(client, "Second plan")
    clash = client.post(
        f"{ME}training-plans/{other['id']}/items/",
        {"kind": "session", "title": "Clash", "starts_at": at(1), "ends_at": at(3)},
        format="json",
    )
    assert clash.status_code == 409 and clash.json()["code"] == "calendar_conflict"
    assert [c["title"] for c in clash.json()["conflicts"]] == ["Multiball", "Serves"]

    # Moving a session into another is refused too; moving it within its own time isn't a clash.
    session = next(i for i in first["items"] if i["title"] == "Multiball")
    item_url = f"{ME}training-plans/{mine['id']}/items/{session['id']}/"
    assert client.patch(item_url, {"ends_at": at(1.75)}, format="json").status_code == 409
    assert client.patch(item_url, {"ends_at": at(1.25)}, format="json").status_code == 200
    assert client.patch(item_url, {"kind": "checklist"}, format="json").status_code == 400

    # Another player can't reach this plan, and their own sessions never clash with this player's.
    someone = logged_in(make_user("x@example.com"))
    add_item(someone, mine["id"], expect=404, kind="checklist", title="Hi")
    assert someone.get(f"{ME}training-plans/{mine['id']}/").status_code == 404
    add_item(someone, plan(someone)["id"], kind="session", title="Same hour", starts_at=at(0), ends_at=at(1))


def test_completion_is_tracked_and_upcoming_sessions_are_listed(db):
    client = logged_in(make_user("player@example.com"))
    mine = plan(client)
    added = add_item(client, mine["id"], kind="checklist", title="Shadow play")
    add_item(client, mine["id"], kind="session", title="Club night", starts_at=at(10), ends_at=at(12))
    item = added["items"][0]
    item_url = f"{ME}training-plans/{mine['id']}/items/{item['id']}/"
    done = client.patch(item_url, {"completed": True}, format="json").json()
    assert done["progress"] == {"done": 1, "total": 2}
    stamp = done["items"][0]["completed_at"]
    # Ticking it again keeps the first time; unticking clears it.
    assert (
        client.patch(item_url, {"completed": True}, format="json").json()["items"][0]["completed_at"] == stamp
    )
    assert client.patch(item_url, {"completed": False}, format="json").json()["progress"]["done"] == 0

    upcoming = client.get(f"{ME}training-sessions/").json()
    assert [(s["title"], s["plan_title"]) for s in upcoming] == [("Club night", "Footwork block")]
    assert client.delete(item_url).json()["progress"] == {"done": 0, "total": 1}
    assert not PlanItem.objects.filter(pk=item["id"]).exists()


def test_a_session_may_not_overlap_a_scheduled_match(staff, club):
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    game = started(staff, club, venue, [["Asha Player"], ["Bakari Player"]])["match"]
    game.scheduled_at = datetime.fromisoformat(at(3))
    game.save(update_fields=["scheduled_at"])
    client = logged_in(person("Asha Player"))
    mine = plan(client)

    clash = client.post(
        f"{ME}training-plans/{mine['id']}/items/",
        {"kind": "session", "title": "Warm-up drills", "starts_at": at(2.5), "ends_at": at(3.25)},
        format="json",
    )
    assert clash.status_code == 409
    assert [c["kind"] for c in clash.json()["conflicts"]] == ["match"]
    # A checklist item for the same day reserves nothing, and a session before the match is fine.
    add_item(client, mine["id"], kind="checklist", title="Warm-up drills")
    add_item(client, mine["id"], kind="session", title="Early hit", starts_at=at(1), ends_at=at(2.5))


def test_the_standard_library_is_seeded_shared_and_read_only(admin, club):
    client = logged_in(make_user("player@example.com"))
    library = client.get("/api/v1/drills/?library=standard").json()
    assert len(library) == 17 and {d["library"] for d in library} == {"standard"}
    falkenberg = next(d for d in library if d["title"] == "Falkenberg")
    assert [(s["stroke"], s["x"]) for s in falkenberg["pattern"]] == [
        ("BH", "left"),
        ("FH pivot", "left"),
        ("FH wide", "right"),
    ]
    assert falkenberg["coaching_points"] and falkenberg["level"] == "intermediate"
    assert client.get(f"/api/v1/drills/{falkenberg['id']}/").json()["title"] == "Falkenberg"
    # Filters, and nobody edits a standard drill through their own library.
    assert {d["category"] for d in client.get("/api/v1/drills/?category=serve").json()} == {"serve"}
    assert (
        client.patch(f"{ME}drills/{falkenberg['id']}/", {"title": "Mine"}, format="json").status_code == 404
    )
    assert (
        client.patch(f"/api/v1/drills/{falkenberg['id']}/", {"title": "X"}, format="json").status_code == 405
    )

    # A plan can start from a standard drill.
    mine = plan(client, "Falkenberg week")
    item = add_item(client, mine["id"], kind="checklist", drill=falkenberg["id"])["items"][0]
    assert item["title"] == "Falkenberg"

    # The library shows a club's drills to its members only.
    staff_client = logged_in(admin)
    body = {"title": "Club special", "instructions": "Ours."}
    club_drill = staff_client.post(f"{ORGS}{club.id}/drills/", body, format="json").json()
    assert club_drill["organization_name"] == "Coast TT Club"
    assert club_drill["id"] not in {d["id"] for d in client.get("/api/v1/drills/").json()}
    assert client.get(f"/api/v1/drills/{club_drill['id']}/").status_code == 404
    assert club_drill["id"] in {d["id"] for d in staff_client.get("/api/v1/drills/").json()}


def test_patterns_are_placed_on_the_table_and_validated(db):
    client = logged_in(make_user("player@example.com"))
    steps = [
        {"hitter": "partner", "stroke": "BH", "x": "left", "depth": "long"},
        {"hitter": "partner", "stroke": "FH middle", "x": "center", "depth": "half"},
    ]
    body = {"title": "Two corners", "instructions": "Move.", "pattern": steps, "level": "beginner"}
    made = client.post(f"{ME}drills/", body, format="json")
    assert made.status_code == 201 and made.json()["pattern"] == steps
    for bad in ({**steps[0], "x": "outside"}, {**steps[0], "hitter": "coach"}, {**steps[0], "stroke": ""}):
        assert client.post(f"{ME}drills/", {**body, "pattern": [bad]}, format="json").status_code == 400
    too_many = {**body, "pattern": steps * 7}
    assert client.post(f"{ME}drills/", too_many, format="json").status_code == 400


def test_clubs_plan_days_and_weeks_for_their_members(admin, club):
    coach, member = make_user("coach@example.com"), make_user("member@example.com")
    add_member(club, coach, "captain")
    add_member(club, member)
    plans = f"{ORGS}{club.id}/training-plans/"
    coaching, client = logged_in(coach), logged_in(member)

    assert (
        client.post(
            plans, {"title": "Tuesday", "period": "day", "starts_on": "2026-12-01"}, format="json"
        ).status_code
        == 403
    )
    assert coaching.post(plans, {"title": "Week", "period": "week"}, format="json").status_code == 400
    week = coaching.post(
        plans, {"title": "Footwork week", "period": "week", "starts_on": "2026-11-30"}, format="json"
    )
    assert week.status_code == 201 and week.json()["ends_on"] == "2026-12-06"
    month = coaching.post(
        plans, {"title": "January", "period": "month", "starts_on": "2027-01-31"}, format="json"
    )
    assert month.json()["ends_on"] == "2027-02-27"
    day = coaching.post(
        plans, {"title": "Tuesday", "period": "day", "starts_on": "2026-12-01"}, format="json"
    ).json()
    assert day["ends_on"] == "2026-12-01"

    # Club sessions are the club's timetable: they reserve no member's time, so overlapping is fine.
    items = f"{plans}{week.json()['id']}/items/"
    standard = client.get("/api/v1/drills/?library=standard").json()[0]
    coaching.post(
        items, {"kind": "session", "title": "Group A", "starts_at": at(0), "ends_at": at(2)}, format="json"
    )
    both = coaching.post(
        items, {"kind": "session", "title": "Group B", "starts_at": at(1), "ends_at": at(3)}, format="json"
    )
    assert both.status_code == 201
    with_drill = coaching.post(items, {"kind": "checklist", "drill": standard["id"]}, format="json").json()
    assert [i["title"] for i in with_drill["items"]] == ["Group A", "Group B", standard["title"]]
    assert client.post(items, {"kind": "checklist", "title": "Mine"}, format="json").status_code == 403

    # Members read the club's plans; outsiders don't; a member's own calendar isn't touched.
    titles = {p["title"] for p in client.get(plans).json()["results"]}
    assert titles == {"Tuesday", "Footwork week", "January"}
    assert client.get(f"{plans}{day['id']}/").json()["period"] == "day"
    assert logged_in(make_user("outsider@example.com")).get(plans).status_code == 403
    assert client.get(f"{ME}training-sessions/").json() == []
    assert coaching.delete(f"{plans}{day['id']}/").status_code == 204


def test_a_plans_goal_recommends_drills_that_teach_it(admin, club):
    client = logged_in(make_user("player@example.com"))
    made = client.post(
        f"{ME}training-plans/", {"title": "Attack first", "goal_skills": ["third_ball"]}, format="json"
    ).json()
    found = client.get(f"{ME}training-plans/{made['id']}/recommendations/").json()
    titles = [r["drill"]["title"] for r in found]
    # The drill built around the skill comes first; every one teaches it.
    assert titles[0] == "Serve and third-ball attack" and "Short backspin serves" in titles
    assert all("third_ball" in r["matched"] for r in found)
    # A drill already in the plan isn't suggested again; no goal, no suggestions.
    add_item(client, made["id"], kind="checklist", drill=found[0]["drill"]["id"])
    again = client.get(f"{ME}training-plans/{made['id']}/recommendations/").json()
    assert found[0]["drill"]["id"] not in [r["drill"]["id"] for r in again]
    assert (
        client.patch(f"{ME}training-plans/{made['id']}/", {"goal_skills": []}, format="json").status_code
        == 200
    )
    assert client.get(f"{ME}training-plans/{made['id']}/recommendations/").json() == []
    bad = client.post(f"{ME}training-plans/", {"title": "X", "goal_skills": ["juggling"]}, format="json")
    assert bad.status_code == 400

    # A club plan is recommended the standard library and the club's own drills, for its training staff.
    staff = logged_in(admin)
    body = {"title": "Club footwork", "instructions": "Ours.", "skills": ["footwork"]}
    ours = staff.post(f"{ORGS}{club.id}/drills/", body, format="json").json()
    week = staff.post(
        f"{ORGS}{club.id}/training-plans/",
        {"title": "Week", "period": "week", "starts_on": "2026-11-30", "goal_skills": ["footwork"]},
        format="json",
    ).json()
    url = f"{ORGS}{club.id}/training-plans/{week['id']}/recommendations/"
    assert ours["id"] in [r["drill"]["id"] for r in staff.get(url).json()]
    assert client.get(url).status_code == 403


def test_a_session_carries_its_running_order_from_warm_up_to_cool_down(db):
    client = logged_in(make_user("player@example.com"))
    library = {d["title"]: d["id"] for d in client.get("/api/v1/drills/").json()}
    mine = plan(client)
    run = [
        {"phase": "warm_up", "drill": library["Dynamic warm-up"], "minutes": 10},
        {"phase": "on_table", "drill": library["Falkenberg"], "minutes": 30},
        {"phase": "off_table", "title": "Skipping intervals", "minutes": 10},
        {"phase": "cool_down", "drill": library["Cool-down stretch"], "minutes": 10},
    ]
    session = add_item(
        client,
        mine["id"],
        kind="session",
        title="Tuesday session",
        starts_at=at(0),
        ends_at=at(1),
        activities=run,
    )["items"][0]
    assert [(a["phase"], a["title"], a["minutes"]) for a in session["activities"]] == [
        ("warm_up", "Dynamic warm-up", 10),
        ("on_table", "Falkenberg", 30),
        ("off_table", "Skipping intervals", 10),
        ("cool_down", "Cool-down stretch", 10),
    ]
    item_url = f"{ME}training-plans/{mine['id']}/items/{session['id']}/"
    # More minutes than the session holds, unknown phases, foreign drills and blank titles are refused.
    too_long = [*run, {"phase": "match_play", "title": "Games", "minutes": 30}]
    assert client.patch(item_url, {"activities": too_long}, format="json").status_code == 400
    assert (
        client.patch(item_url, {"activities": [{"phase": "nap", "title": "Z"}]}, format="json").status_code
        == 400
    )
    assert client.patch(item_url, {"activities": [{"phase": "warm_up"}]}, format="json").status_code == 400
    stranger = (
        logged_in(make_user("other@example.com"))
        .post(f"{ME}drills/", {"title": "Secret", "instructions": "Mine."}, format="json")
        .json()
    )
    foreign = [{"phase": "on_table", "drill": stranger["id"]}]
    assert client.patch(item_url, {"activities": foreign}, format="json").status_code == 400
    assert (
        client.patch(item_url, {"activities": run[:2]}, format="json").json()["items"][0]["activities"][1][
            "title"
        ]
        == "Falkenberg"
    )
