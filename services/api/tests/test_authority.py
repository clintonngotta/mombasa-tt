"""Platform super admins, country and regional officials, and the host club (TASK-094)."""

import pytest

from core.models import Country, Region
from organizations.models import Organization

from .helpers import logged_in, make_official, make_user
from .test_roles import ORGS
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

QUEUE = "/api/v1/tournaments/awaiting-approval/"


@pytest.fixture
def kenya():
    country = Country.objects.create(code="KE", name="Kenya", catalogue_only=True)
    return {
        "country": country,
        "mombasa": Region.objects.create(country=country, name="Mombasa"),
        "kilifi": Region.objects.create(country=country, name="Kilifi"),
    }


@pytest.fixture
def venue(staff, club):
    return make_venue(staff, club)


@pytest.fixture
def coast_club(club, kenya):
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    return club


def official(email, kenya, region=None):
    """An official of the region's body, or of Kenya's national body without a region (TASK-107)."""
    user = make_user(email)
    make_official(user, kenya["country"].code, region.name if region else "")
    return logged_in(user)


def super_admin():
    return logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))


def ready(staff, club, venue, scope):
    return add_event(staff, make_tournament(staff, club, venue, scope=scope), name="Singles")


def ids(response):
    assert response.status_code == 200, response.json()
    return [row["id"] for row in response.json()["results"]]


def test_super_admin_runs_a_club_they_do_not_belong_to(staff, coast_club, venue):
    root = super_admin()
    made = root.post(
        f"{ORGS}{coast_club.id}/tournaments/",
        {"name": "Platform Cup", "starts_on": "2026-12-05", "ends_on": "2026-12-05", "venue_id": venue["id"]},
        format="json",
    )
    assert made.status_code == 201, made.json()
    tournament = add_event(root, made.json(), name="Singles")
    renamed = root.patch(url(tournament), {"name": "Platform Cup 2026"}, format="json")
    assert renamed.status_code == 200 and renamed.json()["name"] == "Platform Cup 2026"
    assert root.patch(f"{ORGS}{coast_club.id}/", {"name": "Coast TT"}, format="json").status_code == 200

    # International tournaments are the platform's alone, and it can publish without a request.
    international = ready(staff, coast_club, venue, "international")
    do(staff, international, "approval/request")
    country = official("country@example.com", {"country": Country.objects.get(pk="KE")})
    # Officials hold no club permissions (OVERSIGHT), so a draft they can't approve isn't theirs to see.
    assert country.post(url(international, "publish"), {}, format="json").status_code == 404
    assert do(root, international, "publish")["approval_status"] == "approved"


def test_each_tier_is_approved_by_its_officials_only(staff, coast_club, venue, kenya):
    regional_official = official("regional@example.com", kenya, kenya["mombasa"])
    country_official = official("country@example.com", kenya)
    outsider = official("kilifi@example.com", kenya, kenya["kilifi"])

    regional = ready(staff, coast_club, venue, "regional")
    national = ready(staff, coast_club, venue, "national")
    for tournament in (regional, national):
        do(staff, tournament, "approval/request")

    assert ids(regional_official.get(QUEUE)) == [regional["id"]]
    assert sorted(ids(country_official.get(QUEUE))) == sorted([regional["id"], national["id"]])
    assert ids(outsider.get(QUEUE)) == []
    assert ids(staff.get(QUEUE)) == []

    assert regional_official.post(url(national, "publish"), {}, format="json").status_code == 404
    assert outsider.post(url(regional, "publish"), {}, format="json").status_code == 404
    declined = do(country_official, regional, "approval/reject", reason="Clashes with the county open.")
    assert declined["approval_status"] == "rejected"
    assert do(country_official, national, "publish")["approval_status"] == "approved"


def test_an_official_cannot_move_a_tournament_into_their_own_tier(staff, coast_club, venue, kenya):
    regional_official = official("regional@example.com", kenya, kenya["mombasa"])
    national = ready(staff, coast_club, venue, "national")
    do(staff, national, "approval/request")

    downgraded = regional_official.patch(url(national), {"scope": "regional"}, format="json")
    assert downgraded.status_code == 404  # a national draft is not theirs to see
    # The host club chooses its own tier, and a change sends the request back.
    moved = staff.patch(url(national), {"scope": "regional"}, format="json")
    assert moved.status_code == 200 and moved.json()["approval_status"] == "not_requested"
    do(staff, national, "approval/request")
    # Now that it is in their tier and waiting for them, the regional official may change the tier, and
    # only the tier: the rest is the host club's.
    assert regional_official.patch(url(national), {"name": "Renamed"}, format="json").status_code == 403
    assert regional_official.patch(url(national), {"scope": "local"}, format="json").status_code == 200


def test_an_official_reads_a_club_but_does_not_run_it(staff, coast_club, venue, kenya):
    """Narrowed authority (user decision, 2026-11-19): the club's page, members' view and tournaments,
    but not its members, roles, settings or competitions."""
    regional_official = official("regional@example.com", kenya, kenya["mombasa"])
    assert regional_official.get(f"{ORGS}{coast_club.id}/committee/").status_code == 200
    assert (
        regional_official.patch(f"{ORGS}{coast_club.id}/", {"name": "Taken"}, format="json").status_code
        == 403
    )
    assert regional_official.get(f"{ORGS}{coast_club.id}/roles/").status_code == 403
    assert regional_official.get(f"{ORGS}{coast_club.id}/members/").status_code == 403
    made = regional_official.post(
        f"{ORGS}{coast_club.id}/tournaments/",
        {"name": "Official Cup", "starts_on": "2026-12-05", "ends_on": "2026-12-05", "venue_id": venue["id"]},
        format="json",
    )
    assert made.status_code == 403
    managed = regional_official.get("/api/v1/me/managed-organizations/").json()
    assert [(m["authority"], m["permissions"]) for m in managed] == [("regional", [])]


def test_a_catalogue_country_takes_only_its_own_regions(admin, kenya):
    client = logged_in(admin)
    body = {"name": "Kilifi Spinners", "kind": "club", "country": "KE", "town": "Malindi"}
    unknown = client.post(ORGS, {**body, "region": "Coast"}, format="json")
    assert unknown.status_code == 400 and "region" in unknown.json()["fields"]
    made = client.post(ORGS, {**body, "region": "  kilifi "}, format="json")
    assert made.status_code == 201, made.json()
    assert Organization.objects.get(pk=made.json()["id"]).region == "Kilifi"


def test_a_region_added_by_the_platform_is_offered_and_accepted(admin, kenya):
    from core.models import City

    added = Region.objects.create(country=kenya["country"], name="Lamu")
    City.objects.create(region=added, name="Lamu Town")
    listed = logged_in(admin).get("/api/v1/geography/countries/KE/").json()
    assert {"name": "Lamu", "cities": ["Lamu Town"]} in listed["regions"]
    made = logged_in(admin).post(
        ORGS,
        {"name": "Lamu TT", "kind": "club", "country": "KE", "region": "Lamu", "town": "Lamu Town"},
        format="json",
    )
    assert made.status_code == 201, made.json()
