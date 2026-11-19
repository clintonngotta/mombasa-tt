"""Facility branch profiles and the facility finder (REQ-044, EVAL-044; TASK-101)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.utils import timezone

from facilities.models import Table
from organizations.models import Organization

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member
from .test_venues import add_table, make_venue, venues_url

pytestmark = pytest.mark.django_db
FINDER = "/api/v1/facilities/"
NAIROBI = ZoneInfo("Africa/Nairobi")


@pytest.fixture
def hall(club, staff):
    """Coast TT Club runs as a facility: a hall with six match and two training tables."""
    Organization.objects.filter(pk=club.pk).update(kind="club_facility")
    venue = make_venue(staff, club, name="Tononoka Hall")
    for number in range(1, 9):
        add_table(staff, club, venue, f"Table {number}")
    for table in Table.objects.filter(venue_id=venue["id"], label__in=["Table 7", "Table 8"]):
        staff.patch(venues_url(club, venue, table={"id": table.id}), {"kind": "training"}, format="json")
    return venue


def publish(staff, club, venue, **body):
    payload = {
        "country": "KE",
        "region": "Mombasa",
        "town": "Mombasa",
        "phone": "+254 700 000000",
        "rules": "Clean shoes only.",
        "amenities": ["Ball hire", "Changing rooms", "Ball hire"],
        "profile": "public",
        **body,
    }
    response = staff.patch(venues_url(club, venue), payload, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def set_hours(staff, club, venue, hours, closures=(), expect=200):
    response = staff.put(
        venues_url(club, venue) + "hours/", {"hours": list(hours), "closures": list(closures)}, format="json"
    )
    assert response.status_code == expect, response.json()
    return response.json()


def around_now(minutes_before=60, minutes_after=60):
    """An opening block containing this moment in Nairobi (kept within one day)."""
    here = timezone.now().astimezone(NAIROBI)
    opens = max(here - timedelta(minutes=minutes_before), here.replace(hour=0, minute=0, second=0))
    closes = min(here + timedelta(minutes=minutes_after), here.replace(hour=23, minute=59, second=0))
    return {"weekday": here.weekday(), "opens": opens.strftime("%H:%M"), "closes": closes.strftime("%H:%M")}


def test_staff_set_up_a_branch_profile(staff, club, hall):
    made = publish(staff, club, hall)
    assert (made["country"], made["region"], made["town"]) == ("KE", "Mombasa", "Mombasa")
    assert made["amenities"] == ["Ball hire", "Changing rooms"]
    assert sorted(t["kind"] for t in made["tables"]).count("training") == 2
    # Kenya takes only catalogue regions.
    call_command("seed_geography", verbosity=0)
    bad = staff.patch(venues_url(club, hall), {"region": "Atlantis"}, format="json")
    assert bad.status_code == 400 and "region" in bad.json()["fields"]
    assert staff.patch(venues_url(club, hall), {"phone": "call me"}, format="json").status_code == 400
    hours = set_hours(
        staff,
        club,
        hall,
        [
            {"weekday": 0, "opens": "08:00", "closes": "12:00"},
            {"weekday": 0, "opens": "14:00", "closes": "21:00"},
        ],
        [{"starts_on": "2026-12-25", "ends_on": "2026-12-26", "reason": "Christmas"}],
    )
    assert [(h["opens"], h["closes"]) for h in hours["opening_hours"]] == [
        ("08:00:00", "12:00:00"),
        ("14:00:00", "21:00:00"),
    ]
    assert hours["closures"][0]["reason"] == "Christmas"
    overlap = [
        {"weekday": 1, "opens": "08:00", "closes": "12:00"},
        {"weekday": 1, "opens": "11:00", "closes": "13:00"},
    ]
    assert "hours" in set_hours(staff, club, hall, overlap, expect=400)["fields"]
    backwards = [{"weekday": 1, "opens": "12:00", "closes": "08:00"}]
    set_hours(staff, club, hall, backwards, expect=400)


def test_only_facility_staff_change_the_profile_and_hours(staff, club, hall):
    member = make_user("member@example.com")
    add_member(club, member)
    client = logged_in(member)
    assert client.patch(venues_url(club, hall), {"profile": "public"}, format="json").status_code == 403
    assert (
        client.put(
            venues_url(club, hall) + "hours/", {"hours": [], "closures": []}, format="json"
        ).status_code
        == 403
    )


def test_the_finder_shows_only_profiles_the_player_may_see(staff, club, hall):
    player = logged_in(make_user("player@example.com"))
    # Hidden by default.
    assert player.get(FINDER).json()["results"] == []
    publish(staff, club, hall, profile="members")
    assert player.get(FINDER).json()["results"] == []
    assert player.get(f"{FINDER}{hall['id']}/").status_code == 404
    member = make_user("member@example.com")
    add_member(club, member)
    assert [f["name"] for f in logged_in(member).get(FINDER).json()["results"]] == ["Tononoka Hall"]
    publish(staff, club, hall, profile="public")
    found = player.get(FINDER).json()["results"]
    assert [(f["name"], f["organization_name"], f["match_tables"], f["training_tables"]) for f in found] == [
        ("Tononoka Hall", "Coast TT Club", 6, 2)
    ]
    assert "phone" not in found[0]
    # A club that isn't a facility isn't in the finder, whatever its venue says.
    other_admin = make_user("other@example.com", display_name="Other")
    other = logged_in(other_admin)
    made = other.post(ORGS, {"name": "Likoni TT", "town": "Mombasa", "kind": "club"}, format="json").json()
    likoni = Organization.objects.get(pk=made["id"])
    venue = make_venue(other, likoni, name="Likoni Hall")
    publish(other, likoni, venue)
    assert [f["name"] for f in player.get(FINDER).json()["results"]] == ["Tononoka Hall"]
    # Signed out: nothing.
    from .conftest import BrowserClient

    assert BrowserClient().get(FINDER).status_code in (401, 403)


def test_the_finder_filters_by_place_and_search(staff, club, hall):
    publish(staff, club, hall)
    player = logged_in(make_user("player@example.com"))
    names = lambda **q: [f["name"] for f in player.get(FINDER, q).json()["results"]]  # noqa: E731
    assert names(city="mombasa") == ["Tononoka Hall"]
    assert names(region="MOMBASA", country="ke") == ["Tononoka Hall"]
    assert names(city="Nairobi") == []
    assert names(search="tononoka") == ["Tononoka Hall"]
    assert names(search="Coast TT") == ["Tononoka Hall"]


def test_open_now_follows_the_hours_the_timezone_and_closures(staff, club, hall):
    if timezone.now().astimezone(NAIROBI).strftime("%H:%M") >= "23:58":
        pytest.skip("No opening block fits in the last minutes of Nairobi's day.")
    publish(staff, club, hall)
    player = logged_in(make_user("player@example.com"))
    path = f"{FINDER}{hall['id']}/"
    assert player.get(path).json()["open_now"] is False  # no hours yet: closed
    set_hours(staff, club, hall, [around_now()])
    assert player.get(path).json()["open_now"] is True
    assert [f["name"] for f in player.get(FINDER, {"open_now": "true"}).json()["results"]] == [
        "Tononoka Hall"
    ]
    # The same hours read in another timezone don't make it open: Nairobi's clock decides.
    Organization.objects.filter(pk=club.pk).update(timezone="America/Lima")
    lima_open = player.get(path).json()["open_now"]
    here = timezone.now()
    lima, nairobi = here.astimezone(ZoneInfo("America/Lima")), here.astimezone(NAIROBI)
    block = around_now()
    inside = (
        block["opens"] <= lima.strftime("%H:%M") < block["closes"] and lima.weekday() == nairobi.weekday()
    )
    assert lima_open is inside
    Organization.objects.filter(pk=club.pk).update(timezone="Africa/Nairobi")
    # A holiday closure today shuts it whatever the hours say, and the profile says why.
    today = timezone.now().astimezone(NAIROBI).date().isoformat()
    set_hours(
        staff, club, hall, [around_now()], [{"starts_on": today, "ends_on": today, "reason": "Holiday"}]
    )
    shown = player.get(path).json()
    assert shown["open_now"] is False
    assert shown["closed_today"]["reason"] == "Holiday"
    assert player.get(FINDER, {"open_now": "true"}).json()["results"] == []
    assert (shown["phone"], shown["rules"], shown["timezone"]) == (
        "+254 700 000000",
        "Clean shoes only.",
        "Africa/Nairobi",
    )
