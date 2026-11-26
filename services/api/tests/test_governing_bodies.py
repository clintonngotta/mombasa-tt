"""Regional and national bodies (REQ-045, EVAL-045, TASK-107): created by a platform super admin with a
first admin; officials are the body members holding `tournaments.approve` (decision D4); appointments
moved into the bodies by migration 0015 and kept as history."""

import importlib

import pytest
from django.apps import apps

from core.models import Country, Region
from organizations.access import effective_permissions, managed_organizations, official_for
from organizations.models import Membership, OfficialAppointment, Organization, seed_roles
from organizations.permissions import Permission, RoleKey

from .helpers import logged_in, make_official, make_user
from .test_roles import ORGS
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
BODIES = "/api/v1/regional-bodies/"
QUEUE = "/api/v1/tournaments/awaiting-approval/"
APPROVE = Permission.TOURNAMENTS_APPROVE


@pytest.fixture
def kenya():
    country = Country.objects.create(code="KE", name="Kenya", catalogue_only=True)
    return {
        "country": country,
        "mombasa": Region.objects.create(country=country, name="Mombasa"),
        "kilifi": Region.objects.create(country=country, name="Kilifi"),
    }


@pytest.fixture
def root():
    return logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))


@pytest.fixture
def coast_club(club, kenya):
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    return club


def ready(staff, club, scope, venue):
    tournament = add_event(staff, make_tournament(staff, club, venue, scope=scope), name="Singles")
    do(staff, tournament, "approval/request")
    return tournament


def ids(response):
    assert response.status_code == 200, response.json()
    return [row["id"] for row in response.json()["results"]]


def test_a_platform_super_admin_creates_each_body_with_its_first_admin(root, kenya):
    chair = make_user("chair@example.com")
    head = make_user("head@example.com")
    mombasa = {"name": "Mombasa Region TT", "country": "KE", "region": "Mombasa"}
    regional = root.post(BODIES, {**mombasa, "admin_email": "CHAIR@example.com"}, format="json")
    assert regional.status_code == 201, regional.json()
    assert regional.json()["kind"] == "regional_body" and regional.json()["region"] == "Mombasa"
    national = root.post(
        BODIES,
        {"name": "Kenya TT", "kind": "national_body", "country": "ke", "admin_email": head.email},
        format="json",
    )
    assert national.status_code == 201, national.json()
    assert (national.json()["country"], national.json()["region"]) == ("KE", "")

    for body_id, user in ((regional.json()["id"], chair), (national.json()["id"], head)):
        body = Organization.objects.get(pk=body_id)
        admin = Membership.objects.get(organization=body, user=user)
        assert admin.roles.filter(key=RoleKey.ADMIN).exists()
        assert body.roles.get(key=RoleKey.OFFICIAL).permission_set == {APPROVE}
        assert APPROVE in effective_permissions(user, body)
    # Clubs don't get the Official template.
    club = Organization.objects.create(name="Plain Club", town="Mombasa")
    seed_roles(club)
    assert not club.roles.filter(key=RoleKey.OFFICIAL).exists()

    # One body per region and one per country.
    twice = {"name": "Kenya TT 2", "kind": "national_body", "country": "KE", "admin_email": head.email}
    assert root.post(BODIES, twice, format="json").status_code == 409
    again = {"name": "Mombasa 2", "country": "KE", "region": "Mombasa", "admin_email": chair.email}
    assert root.post(BODIES, again, format="json").status_code == 409
    # The input is checked: a region, a country, an existing active account.
    no_region = root.post(BODIES, {"name": "X", "country": "KE", "admin_email": chair.email}, format="json")
    assert no_region.status_code == 400 and "region" in no_region.json()["fields"]
    elsewhere = {"name": "X", "country": "KE", "region": "Lagos", "admin_email": chair.email}
    assert "region" in root.post(BODIES, elsewhere, format="json").json()["fields"]
    no_country = root.post(
        BODIES, {"name": "X", "kind": "national_body", "admin_email": chair.email}, format="json"
    )
    assert no_country.status_code == 400 and "country" in no_country.json()["fields"]
    unknown = {"name": "Kilifi TT", "country": "KE", "region": "Kilifi", "admin_email": "nobody@example.com"}
    assert root.post(BODIES, unknown, format="json").status_code == 400
    # Nobody else creates one, not even a body's own admin.
    kilifi = {"name": "Kilifi TT", "country": "KE", "region": "Kilifi", "admin_email": chair.email}
    assert logged_in(chair).post(BODIES, kilifi, format="json").status_code == 403
    listed = logged_in(make_user("anyone@example.com")).get(BODIES).json()
    assert [(b["name"], b["kind"]) for b in listed] == [
        ("Kenya TT", "national_body"),
        ("Mombasa Region TT", "regional_body"),
    ]


def test_approval_follows_the_body_and_its_permission(staff, coast_club, kenya):
    venue = make_venue(staff, coast_club)
    regional = ready(staff, coast_club, "regional", venue)
    national = ready(staff, coast_club, "national", venue)

    # A member of the region's body without the approval permission is no official.
    secretary_user = make_user("secretary@example.com")
    body = make_official(secretary_user, "KE", "Mombasa", role=None)
    secretary = logged_in(secretary_user)
    assert ids(secretary.get(QUEUE)) == []
    assert secretary.post(url(regional, "publish"), {}, format="json").status_code == 404
    assert not official_for(secretary_user, coast_club)

    # Given the body's Official role they approve the region's tournaments, and only those.
    membership = Membership.objects.get(organization=body, user=secretary_user)
    membership.roles.add(body.roles.get(key=RoleKey.OFFICIAL))
    assert ids(secretary.get(QUEUE)) == [regional["id"]]
    assert secretary.post(url(national, "publish"), {}, format="json").status_code == 404

    # The national body's official approves national tournaments of the country.
    country_user = make_user("country@example.com")
    make_official(country_user, "KE")
    country = logged_in(country_user)
    assert sorted(ids(country.get(QUEUE))) == sorted([regional["id"], national["id"]])
    assert do(country, national, "publish")["approval_status"] == "approved"

    # Another region's official has nothing here.
    kilifi_user = make_user("kilifi@example.com")
    make_official(kilifi_user, "KE", "Kilifi")
    assert ids(logged_in(kilifi_user).get(QUEUE)) == []

    # Leaving the body ends the authority.
    membership.status = Membership.Status.LEFT
    membership.save(update_fields=["status"])
    assert ids(secretary.get(QUEUE)) == []
    assert not official_for(secretary_user, coast_club)


def test_officials_oversee_their_jurisdiction_not_their_own_body(staff, coast_club, kenya):
    user = make_user("regional@example.com")
    body = make_official(user, "KE", "Mombasa")
    overseen = set(managed_organizations(user))
    assert coast_club in overseen and body not in overseen
    managed = logged_in(user).get("/api/v1/me/managed-organizations/").json()
    assert [(m["organization"]["id"], m["authority"]) for m in managed] == [(str(coast_club.id), "regional")]


def test_a_club_role_cannot_hold_tournament_approval(admin, club, kenya):
    client = logged_in(admin)
    refused = client.post(
        f"{ORGS}{club.id}/roles/", {"name": "Approver", "permissions": [APPROVE]}, format="json"
    )
    assert refused.status_code == 400 and "permissions" in refused.json()["fields"]
    catalogue = {row["code"]: row["body_only"] for row in client.get(f"{ORGS}permissions/").json()}
    assert catalogue[APPROVE] is True and catalogue[Permission.MEMBERS_MANAGE] is False

    # A club admin holds every permission but approves nothing: only bodies count.
    coast = club
    coast.country, coast.region = "KE", "Mombasa"
    coast.save(update_fields=["country", "region"])
    assert not official_for(admin, coast)

    # A body's admin can make a role with it.
    chair = make_user("chair@example.com")
    body = make_official(chair, "KE", "Mombasa", role=RoleKey.ADMIN)
    made = logged_in(chair).post(
        f"{ORGS}{body.id}/roles/", {"name": "Approver", "permissions": [APPROVE]}, format="json"
    )
    assert made.status_code == 201, made.json()


def test_the_national_body_works_for_every_club_of_its_country(coast_club, admin, kenya):
    head = make_user("head@example.com")
    national = make_official(head, "KE", role=RoleKey.ADMIN)
    kilifi_admin = make_user("kilifi@example.com")
    kilifi = Organization.objects.create(
        name="Kilifi Spinners", town="Malindi", country="KE", region="Kilifi"
    )
    Membership.objects.create(organization=kilifi, user=kilifi_admin).roles.add(
        seed_roles(kilifi)[RoleKey.ADMIN]
    )
    clubs = logged_in(head).get(f"{ORGS}{national.id}/region-clubs/").json()
    assert sorted(c["name"] for c in clubs) == ["Coast TT Club", "Kilifi Spinners"]
    agm = {"kind": "meeting", "title": "National AGM", "starts_on": "2027-03-01"}
    made = logged_in(head).post(f"{ORGS}{national.id}/agenda/", agm, format="json")
    assert made.status_code == 201, made.json()
    for user in (admin, kilifi_admin):
        assert [i["title"] for i in logged_in(user).get("/api/v1/me/agenda/").json()] == ["National AGM"]


def test_migration_moves_each_appointment_into_its_body(kenya):
    """0015: a regional appointment joins its region's body, a country appointment the national body,
    both made if missing; the first appointee of a new body is its admin, the rest Official; an existing
    body keeps its admin; someone with two appointments joins both bodies."""
    migration = importlib.import_module("organizations.migrations.0015_governing_bodies")
    country, mombasa, kilifi = kenya["country"], kenya["mombasa"], kenya["kilifi"]
    existing_admin = make_user("existing@example.com")
    existing = make_official(existing_admin, "KE", "Kilifi", role=RoleKey.ADMIN)
    existing.roles.filter(key=RoleKey.OFFICIAL).delete()  # bodies made before 0015 had no Official role

    first, second, head, both, joiner = (make_user(f"{n}@example.com") for n in range(5))
    OfficialAppointment.objects.create(user=first, country=country, region=mombasa)
    OfficialAppointment.objects.create(user=second, country=country, region=mombasa)
    OfficialAppointment.objects.create(user=head, country=country)
    OfficialAppointment.objects.create(user=both, country=country, region=mombasa)
    OfficialAppointment.objects.create(user=both, country=country)
    OfficialAppointment.objects.create(user=joiner, country=country, region=kilifi)
    OfficialAppointment.objects.create(user=existing_admin, country=country, region=kilifi)

    migration.appointments_to_bodies(apps, None)
    migration.appointments_to_bodies(apps, None)  # running it twice changes nothing

    regional = Organization.objects.get(kind="regional_body", country="KE", region="Mombasa")
    national = Organization.objects.get(kind="national_body", country="KE")

    def keys(body, user):
        membership = Membership.objects.get(organization=body, user=user, status="active")
        return sorted(membership.roles.values_list("key", flat=True))

    assert keys(regional, first) == ["admin"]
    assert keys(regional, second) == ["official"] and keys(regional, both) == ["official"]
    assert keys(national, head) == ["admin"] and keys(national, both) == ["official"]
    assert keys(existing, joiner) == ["official"] and keys(existing, existing_admin) == ["admin"]
    assert existing.roles.filter(key=RoleKey.OFFICIAL).count() == 1
    clubs = Organization.objects.create(name="Coast", town="Mombasa", country="KE", region="Mombasa")
    for user in (first, second, both):
        assert official_for(user, clubs)
    assert official_for(head, clubs, country_only=True) and not official_for(second, clubs, country_only=True)
    assert OfficialAppointment.objects.count() == 7  # history stays
