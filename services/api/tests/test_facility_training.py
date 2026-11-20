"""Facility training slots, joining them, and a branch's schedule (REQ-044, EVAL-044; TASK-103)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from facilities.models import Table
from organizations.models import Organization
from training.models import ClubSession, SessionInvitation

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member
from .test_tournaments import add_event, do, make_tournament
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db
OPEN = "/api/v1/open-sessions/"


@pytest.fixture
def hall(club, staff):
    """A facility with six match tables and two training tables."""
    Organization.objects.filter(pk=club.pk).update(kind="facility")
    club.refresh_from_db()
    venue = make_venue(staff, club, name="Tononoka Hall")
    for number in range(1, 9):
        add_table(staff, club, venue, f"Table {number}")
    Table.objects.filter(venue_id=venue["id"], label__in=["Table 7", "Table 8"]).update(kind="training")
    staff.patch(f"{ORGS}{club.id}/venues/{venue['id']}/", {"profile": "public"}, format="json")
    return venue


def tables(hall, kind):
    return list(Table.objects.filter(venue_id=hall["id"], kind=kind).order_by("position"))


def slot(staff, club, on, expect=201, days=2, hours=2, **body):
    # 10:00 in Nairobi, so a session never crosses local midnight whenever the suite runs.
    nairobi = timezone.now().astimezone(ZoneInfo("Africa/Nairobi"))
    starts = (nairobi + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0)
    payload = {
        "title": "Juniors",
        "table_ids": [str(t.id) for t in on],
        "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=hours)).isoformat(),
        "open_to_players": True,
        "level": "beginner",
        "fee_minor": 30000,
        "capacity": 2,
        **body,
    }
    response = staff.post(f"{ORGS}{club.id}/club-sessions/", payload, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_a_weekly_schedule_on_training_tables_with_coach_level_and_fee(staff, club, hall, admin):
    refused = slot(staff, club, tables(hall, "match")[:1], expect=400)
    assert "table_ids" in refused["fields"]
    made = slot(staff, club, tables(hall, "training"), repeat_weeks=4, coach_id=str(admin.id))
    assert (made["coach_name"], made["level"], made["fee_minor"], made["fee_currency"]) == (
        "Club Admin",
        "beginner",
        30000,
        "KES",
    )
    series = ClubSession.objects.filter(series=made["series"]).order_by("starts_at")
    assert series.count() == 4
    gaps = {(b.starts_at - a.starts_at) for a, b in zip(series, series[1:], strict=False)}
    assert gaps == {timedelta(weeks=1)}
    outsider = make_user("coach@example.com")
    assert (
        "coach_id"
        in slot(staff, club, tables(hall, "training"), expect=400, days=40, coach_id=str(outsider.id))[
            "fields"
        ]
    )


def test_one_clash_keeps_the_whole_series_out(staff, club, hall):
    training = tables(hall, "training")
    slot(staff, club, training[:1], days=16, title="Week three blocker")
    clash = slot(staff, club, training, expect=409, repeat_weeks=4, title="Seniors")
    assert clash["code"] == "table_unavailable"
    assert [c["title"] for c in clash["conflicts"]] == ["Week three blocker"]
    assert not ClubSession.objects.filter(title="Seniors").exists()


def test_a_tournament_can_not_take_tables_training_holds(staff, club, hall):
    training = tables(hall, "training")
    made = slot(staff, club, training, days=3)
    local = ClubSession.objects.get(pk=made["id"]).starts_at.astimezone(ZoneInfo("Africa/Nairobi"))
    day = local.date().isoformat()
    cup = make_tournament(staff, club, hall, starts_on=day, ends_on=day, timezone="Africa/Nairobi")
    add_event(staff, cup)
    path = f"/api/v1/tournaments/{cup['id']}/schedule/sessions/"
    body = {
        "day": day,
        "starts": local.strftime("%H:%M"),
        "ends": (local + timedelta(hours=1)).strftime("%H:%M"),
        "table_ids": [str(t.id) for t in training],
    }
    refused = staff.post(path, body, format="json")
    assert refused.status_code == 409, refused.json()
    assert refused.json()["code"] == "table_unavailable"
    assert [c["title"] for c in refused.json()["conflicts"]] == ["Juniors"]
    # The match tables are free then.
    body["table_ids"] = [str(t.id) for t in tables(hall, "match")]
    assert staff.post(path, body, format="json").status_code == 201
    assert ClubSession.objects.get(pk=made["id"]).status == "scheduled"


def test_any_player_joins_an_open_slot_once_and_capacity_holds(staff, club, hall):
    made = slot(staff, club, tables(hall, "training"))
    closed = slot(staff, club, tables(hall, "training"), days=5, open_to_players=False, title="Squad only")
    players = [logged_in(make_user(f"p{n}@example.com", display_name=f"Player {n}")) for n in range(3)]
    listed = players[0].get(OPEN).json()["results"]
    assert [s["title"] for s in listed] == ["Juniors"]
    assert (listed[0]["places_left"], listed[0]["fee_minor"], listed[0]["organization_name"]) == (
        2,
        30000,
        "Coast TT Club",
    )
    joined = players[0].post(f"{OPEN}{made['id']}/join/").json()
    assert (joined["joined"], joined["places_left"]) == (True, 1)
    assert players[0].post(f"{OPEN}{made['id']}/join/").json()["places_left"] == 1  # twice is harmless
    players[1].post(f"{OPEN}{made['id']}/join/")
    full = players[2].post(f"{OPEN}{made['id']}/join/")
    assert full.status_code == 409 and full.json()["code"] == "session_full"
    assert players[2].post(f"{OPEN}{closed['id']}/join/").status_code == 404
    left = players[0].post(f"{OPEN}{made['id']}/leave/").json()
    assert (left["joined"], left["places_left"]) == (False, 1)
    assert players[2].post(f"{OPEN}{made['id']}/join/").status_code == 200
    assert SessionInvitation.objects.filter(session_id=made["id"], status="accepted").count() == 2


def test_joining_checks_the_players_calendar(staff, club, hall):
    made = slot(staff, club, tables(hall, "training"))
    player_user = make_user("p@example.com")
    player = logged_in(player_user)
    plan = player.post("/api/v1/me/training-plans/", {"title": "Mine"}, format="json").json()
    session = ClubSession.objects.get(pk=made["id"])
    player.post(
        f"/api/v1/me/training-plans/{plan['id']}/items/",
        {
            "kind": "session",
            "title": "Solo",
            "starts_at": session.starts_at.isoformat(),
            "ends_at": session.ends_at.isoformat(),
        },
        format="json",
    )
    clash = player.post(f"{OPEN}{made['id']}/join/")
    assert clash.status_code == 409 and clash.json()["code"] == "calendar_conflict"


def test_the_branch_schedule_lists_training_public_activities_and_tournaments_in_order(staff, club, hall):
    slot(staff, club, tables(hall, "training"), days=4, title="Open training")
    slot(staff, club, tables(hall, "training"), days=6, open_to_players=False, title="Members only")
    member = make_user("m@example.com")
    add_member(club, member)
    soon = (timezone.now() + timedelta(days=2)).replace(microsecond=0)
    for title, public in (("Anniversary", True), ("Members night", False)):
        made = staff.post(
            f"{ORGS}{club.id}/activities/",
            {
                "title": title,
                "kind": "anniversary",
                "starts_at": soon.isoformat(),
                "ends_at": (soon + timedelta(hours=3)).isoformat(),
                "public": public,
            },
            format="json",
        ).json()
        staff.post(f"{ORGS}{club.id}/activities/{made['id']}/publish/", {}, format="json")
    day = (timezone.now() + timedelta(days=9)).date().isoformat()
    cup = make_tournament(staff, club, hall, starts_on=day, ends_on=day, timezone="Africa/Nairobi")
    add_event(staff, cup)
    do(staff, cup, "publish")
    player = logged_in(make_user("anyone@example.com"))
    items = player.get(f"/api/v1/facilities/{hall['id']}/schedule/").json()
    assert [(i["kind"], i["title"]) for i in items] == [
        ("activity", "Anniversary"),
        ("training", "Open training"),
        ("tournament", "Coast Open"),
    ]
