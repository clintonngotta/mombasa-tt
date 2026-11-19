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
