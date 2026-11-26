"""Clubs and facility branches near a point (REQ-004, REQ-044): by distance, in a request body, with
the same visibility rules as the lists."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.throttling import ScopedThrottle
from organizations.models import Organization

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_club_discovery import place
from .test_facilities import publish
from .test_roles import ORGS, add_member, create_club
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
CLUBS_NEAR = "/api/v1/organizations/nearby/"
FACILITIES_NEAR = "/api/v1/facilities/nearby/"
# Moi Avenue, Mombasa.
HERE = {"latitude": -4.0635, "longitude": 39.6682}
# Degrees of latitude: 0.001 is about 111 m.
STEP = 0.001


def north(metres_in_hundreds: float) -> dict:
    latitude = round(HERE["latitude"] + metres_in_hundreds * STEP * 0.9, 6)
    return {"latitude": latitude, "longitude": HERE["longitude"]}


@pytest.fixture
def player():
    return logged_in(make_user("seeker@example.com", display_name="Seeker"))


@pytest.fixture
def clubs(admin):
    """Clubs about 200 m, 900 m and 8 km north, one without a map position, and a facility next door."""
    place(create_club(admin, "Two Hundred"), town="Mombasa", **north(2))
    place(create_club(admin, "Nine Hundred"), town="Mombasa", **north(9))
    place(create_club(admin, "Eight Kilometres"), town="Bamburi", **north(80))
    place(create_club(admin, "No Position"), town="Mombasa")
    place(create_club(admin, "Just A Hall"), town="Mombasa", kind=Organization.Kind.FACILITY, **north(1))
    place(create_club(admin, "Coach Desk"), town="Mombasa", kind=Organization.Kind.COACHING, **north(1))


def found(response) -> list[str]:
    assert response.status_code == 200, response.json()
    return [row["name"] for row in response.json()["results"]]


def test_clubs_within_300_metres_then_wider_nearest_first(player, clubs):
    assert found(player.post(CLUBS_NEAR, {**HERE, "radius_m": 300}, format="json")) == ["Two Hundred"]
    wider = player.post(CLUBS_NEAR, {**HERE, "radius_m": 1000}, format="json")
    assert found(wider) == ["Two Hundred", "Nine Hundred"]
    assert wider.json()["count"] == 2
    distances = [row["distance_m"] for row in wider.json()["results"]]
    assert 180 <= distances[0] <= 220 and 880 <= distances[1] <= 920
    # Facilities, coaching desks and clubs with no position are never in the answer.
    assert found(player.post(CLUBS_NEAR, {**HERE, "radius_m": 50000}, format="json")) == [
        "Two Hundred",
        "Nine Hundred",
        "Eight Kilometres",
    ]
    assert found(
        player.post(CLUBS_NEAR, {**HERE, "radius_m": 50000, "search": "bamburi"}, format="json")
    ) == ["Eight Kilometres"]


def test_a_club_on_the_spot_is_zero_metres_away(player, admin):
    place(create_club(admin, "Right Here"), **HERE)
    rows = player.post(CLUBS_NEAR, {**HERE, "radius_m": 100}, format="json").json()["results"]
    assert [(row["name"], row["distance_m"]) for row in rows] == [("Right Here", 0)]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"latitude": 91, "longitude": 0, "radius_m": 300}, "latitude"),
        ({"latitude": 0, "longitude": 181, "radius_m": 300}, "longitude"),
        ({"latitude": 0, "longitude": 0, "radius_m": 99}, "radius_m"),
        ({"latitude": 0, "longitude": 0, "radius_m": 50001}, "radius_m"),
        ({"latitude": 0, "longitude": 0}, "radius_m"),
        ({"latitude": "north", "longitude": 0, "radius_m": 300}, "latitude"),
        ({**HERE, "radius_m": 300, "search": "x" * 121}, "search"),
        ({**HERE, "radius_m": 300, "user_id": "someone-else"}, "user_id"),
    ],
)
def test_the_search_is_checked_on_the_server(player, body, field):
    for url in (CLUBS_NEAR, FACILITIES_NEAR):
        response = player.post(url, body, format="json")
        assert response.status_code == 400, response.json()
        assert field in response.json()["fields"]


def test_signed_out_callers_get_nothing_and_a_position_is_never_read_from_the_url(player, clubs):
    for url in (CLUBS_NEAR, FACILITIES_NEAR):
        assert BrowserClient().post(url, {**HERE, "radius_m": 300}, format="json").status_code in (401, 403)
        # A GET with the point in the query string isn't a nearby search at all.
        assert player.get(url, {**HERE, "radius_m": 300}).status_code in (404, 405)


def test_the_search_is_limited_per_player(player, clubs, monkeypatch):
    monkeypatch.setitem(ScopedThrottle.THROTTLE_RATES, "nearby", "2/min")
    body = {**HERE, "radius_m": 300}
    assert player.post(CLUBS_NEAR, body, format="json").status_code == 200
    # Clubs and facilities share the allowance.
    assert player.post(FACILITIES_NEAR, body, format="json").status_code == 200
    assert player.post(CLUBS_NEAR, body, format="json").status_code == 429
    # Another player has their own count, and the ordinary list isn't limited by it.
    other = logged_in(make_user("other@example.com"))
    assert other.post(CLUBS_NEAR, body, format="json").status_code == 200
    assert player.get(ORGS).status_code == 200


def facility(owner_email: str, name: str, position: dict, **profile):
    owner = make_user(owner_email, display_name=name)
    client = logged_in(owner)
    made = client.post(ORGS, {"name": f"{name} Ltd", "town": "Mombasa", "kind": "facility"}, format="json")
    organization = Organization.objects.get(pk=made.json()["id"])
    venue = make_venue(client, organization, name=name)
    publish(client, organization, venue, **position, **profile)
    return organization, client, venue


def test_branches_near_follow_the_finders_visibility(player):
    facility("a@example.com", "Public Hall", north(2))
    members_only, _, _ = facility("b@example.com", "Members Hall", north(2.5), profile="members")
    facility("c@example.com", "Hidden Hall", north(1), profile="hidden")
    facility("d@example.com", "Far Hall", north(80))
    body = {**HERE, "radius_m": 300}
    assert found(player.post(FACILITIES_NEAR, body, format="json")) == ["Public Hall"]
    # A members-only branch shows to its members alone.
    member = make_user("member@example.com")
    add_member(members_only, member)
    assert found(logged_in(member).post(FACILITIES_NEAR, body, format="json")) == [
        "Public Hall",
        "Members Hall",
    ]
    row = player.post(FACILITIES_NEAR, body, format="json").json()["results"][0]
    assert 180 <= row["distance_m"] <= 220
    assert "phone" not in row
    # No opening hours are set, so nothing is open now.
    assert found(player.post(FACILITIES_NEAR, {**body, "open_now": True}, format="json")) == []


def test_the_search_costs_the_same_however_many_branches_match(player):
    facility("a@example.com", "Hall One", north(1))
    body = {**HERE, "radius_m": 1000}
    with CaptureQueriesContext(connection) as one:
        assert len(found(player.post(FACILITIES_NEAR, body, format="json"))) == 1
    facility("b@example.com", "Hall Two", north(2))
    facility("c@example.com", "Hall Three", north(3))
    with CaptureQueriesContext(connection) as three:
        assert len(found(player.post(FACILITIES_NEAR, body, format="json"))) == 3
    assert len(three) == len(one)
