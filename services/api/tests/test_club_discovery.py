"""Finding a club to join: search by name, region and city, and a club's profile with its location,
description, training hours and upcoming tournaments; nothing else until the player joins."""

from datetime import date, timedelta

import pytest

from competitions.models import Tournament
from organizations.models import Organization, Role
from organizations.permissions import RoleKey

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, create_club
from .test_venues import make_venue

pytestmark = pytest.mark.django_db


def place(org, country="KE", region="Mombasa", town="Mombasa", **extra) -> Organization:
    Organization.objects.filter(pk=org.pk).update(country=country, region=region, town=town, **extra)
    org.refresh_from_db()
    return org


def names(response) -> list[str]:
    assert response.status_code == 200, response.json()
    return [org["name"] for org in response.json()["results"]]


@pytest.fixture
def player():
    return logged_in(make_user("seeker@example.com", display_name="Seeker"))


@pytest.fixture
def coast(admin):
    clubs = [
        place(create_club(admin, "Coast Spinners"), town="Nyali"),
        place(create_club(admin, "Likoni Smashers"), town="Likoni"),
        place(create_club(admin, "Kilifi Loopers"), region="Kilifi", town="Malindi"),
        place(create_club(admin, "Nairobi Chiefs"), region="Nairobi", town="Nairobi"),
    ]
    place(create_club(admin, "Nyali Sports Hall"), town="Nyali", kind=Organization.Kind.FACILITY)
    return clubs


def test_players_list_clubs_by_region_city_name_and_kind(player, coast):
    assert names(
        player.get(ORGS, {"country": "ke", "region": "mombasa", "kind": ["club", "club_facility"]})
    ) == [
        "Coast Spinners",
        "Likoni Smashers",
    ]
    assert names(player.get(ORGS, {"region": "Mombasa", "city": "nyali"})) == [
        "Coast Spinners",
        "Nyali Sports Hall",
    ]
    assert names(player.get(ORGS, {"region": "Mombasa", "search": "smash"})) == ["Likoni Smashers"]
    # A search term alone also matches the region, so "Kilifi" finds the club in Malindi.
    assert names(player.get(ORGS, {"search": "kilifi"})) == ["Kilifi Loopers"]
    assert names(player.get(ORGS, {"country": "TZ"})) == []
    # An unknown kind is ignored rather than hiding everything.
    assert len(names(player.get(ORGS, {"kind": "stadium"}))) == 5


def test_a_club_profile_shows_where_it_is_what_it_is_and_when_it_trains(admin, staff, club, player):
    place(club, town="Nyali", directions="Behind Nyali Centre")
    staff.patch(f"{ORGS}{club.id}/", {"description": "Friendly club, all levels."}, format="json")
    hall = make_venue(staff, club, address="Links Road")
    retired = make_venue(staff, club, name="Old hall")
    staff.patch(f"{ORGS}{club.id}/venues/{retired['id']}/", {"active": False}, format="json")
    hours = staff.put(
        f"{ORGS}{club.id}/training-hours/",
        {
            "hours": [
                {"weekday": 5, "starts": "09:00", "ends": "12:00", "label": "Juniors", "venue": hall["id"]},
                {"weekday": 1, "starts": "18:00", "ends": "20:30"},
            ]
        },
        format="json",
    )
    assert hours.status_code == 200, hours.json()

    today = date.today()
    shown = {"published": today + timedelta(days=10), "in_progress": today}
    for status, starts in shown.items():
        Tournament.objects.create(
            organization=club,
            name=f"Open {status}",
            starts_on=starts,
            ends_on=starts,
            timezone=club.timezone,
            status=status,
        )
    for status, starts in {
        "draft": today,
        "cancelled": today,
        "completed": today - timedelta(days=9),
    }.items():
        Tournament.objects.create(
            organization=club,
            name=f"Hidden {status}",
            starts_on=starts,
            ends_on=starts,
            timezone=club.timezone,
            status=status,
        )
    Tournament.objects.create(
        organization=club,
        name="Last month",
        starts_on=today - timedelta(days=30),
        ends_on=today - timedelta(days=29),
        timezone=club.timezone,
        status="published",
    )

    profile = player.get(f"{ORGS}{club.id}/profile/")
    assert profile.status_code == 200
    body = profile.json()
    assert (body["town"], body["region"], body["directions"]) == ("Nyali", "Mombasa", "Behind Nyali Centre")
    assert body["description"] == "Friendly club, all levels."
    assert [v["name"] for v in body["venues"]] == ["Makadara Hall"]
    assert [(h["weekday"], h["starts"], h["label"], h["venue_name"]) for h in body["training_hours"]] == [
        (1, "18:00:00", "", None),
        (5, "09:00:00", "Juniors", "Makadara Hall"),
    ]
    assert [t["name"] for t in body["upcoming_tournaments"]] == ["Open in_progress", "Open published"]
    # Directory-level data only: no members, roles, plans or money.
    assert set(body) == {
        "id",
        "name",
        "kind",
        "country",
        "region",
        "town",
        "directions",
        "latitude",
        "longitude",
        "description",
        "timezone",
        "venues",
        "training_hours",
        "upcoming_tournaments",
    }


def test_outsiders_see_the_profile_but_not_the_clubs_training_or_members(club, player, client):
    assert player.get(f"{ORGS}{club.id}/profile/").status_code == 200
    assert player.get(f"{ORGS}{club.id}/training-hours/").status_code == 200
    for path in ("training-plans/", "drills/", "members/", "venues/"):
        assert player.get(f"{ORGS}{club.id}/{path}").status_code in (403, 404), path
    assert client.get(f"{ORGS}{club.id}/profile/").status_code in (401, 403)


def test_only_training_staff_set_training_hours_and_only_with_the_clubs_venues(admin, staff, club, player):
    url = f"{ORGS}{club.id}/training-hours/"
    one = {"hours": [{"weekday": 2, "starts": "17:00", "ends": "19:00"}]}

    coach = make_user("coach@example.com")
    member = make_user("member@example.com")
    add_member(club, member, RoleKey.MEMBER)
    membership = add_member(club, coach, RoleKey.MEMBER)
    assert logged_in(member).put(url, one, format="json").status_code == 403
    assert player.put(url, one, format="json").status_code == 403
    membership.roles.add(
        Role.objects.create(organization=club, name="Coach", permissions=["training.manage"])
    )
    assert logged_in(coach).put(url, one, format="json").status_code == 200

    other = create_club(make_user("other@example.com"), "Other Club")
    their_hall = make_venue(logged_in(other.memberships.get().user), other)
    bad = [
        {"weekday": 7, "starts": "09:00", "ends": "10:00"},
        {"weekday": 1, "starts": "10:00", "ends": "09:00"},
        {"weekday": 1, "starts": "09:00", "ends": "10:00", "venue": their_hall["id"]},
    ]
    for hour in bad:
        response = staff.put(url, {"hours": [hour]}, format="json")
        assert response.status_code == 400, hour
    too_many = [{"weekday": d % 7, "starts": "09:00", "ends": "10:00"} for d in range(43)]
    assert staff.put(url, {"hours": too_many}, format="json").status_code == 400
    # A refused list leaves the saved hours alone; an empty list clears them.
    assert [h["weekday"] for h in staff.get(url).json()] == [2]
    assert staff.put(url, {"hours": []}, format="json").json() == []
