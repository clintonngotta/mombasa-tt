"""The platform's back office (REQ-056, EVAL-056): /api/v1/platform/ is for platform super admins alone
and doesn't exist for anyone else; accounts are switched off and on and given platform authority there;
the place catalogue is edited there, and renamed places carry their clubs and players with them."""

import pytest

from accounts.models import User
from core.models import City, Country, Region
from organizations.models import Membership, Organization, seed_roles
from organizations.permissions import RoleKey
from profiles.models import PlayerProfile

from .conftest import PASSWORD, BrowserClient
from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db
P = "/api/v1/platform/"


@pytest.fixture
def root_user():
    return make_user("root@example.com", display_name="Root Owner", is_superuser=True, is_staff=True)


@pytest.fixture
def root(root_user):
    return logged_in(root_user)


@pytest.fixture
def kenya():
    country, _ = Country.objects.get_or_create(code="KE", defaults={"name": "Kenya"})
    region = Region.objects.create(country=country, name="Pwani Test")
    return {"country": country, "region": region, "city": City.objects.create(region=region, name="Mtwapa")}


def make_club(name="Coast Spinners", admin=None, **extra):
    club = Organization.objects.create(name=name, town=extra.pop("town", "Mombasa"), **extra)
    roles = seed_roles(club)
    if admin:
        Membership.objects.create(organization=club, user=admin).roles.add(roles[RoleKey.ADMIN])
    return club


ROUTES = [
    ("get", "overview/"),
    ("get", "accounts/"),
    ("get", "organizations/"),
    ("get", "countries/KE/"),
    ("patch", "countries/KE/"),
    ("post", "countries/KE/regions/"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_the_back_office_is_closed_to_everyone_else(method, path, kenya):
    assert getattr(BrowserClient(), method)(P + path, {}, format="json").status_code == 401
    # A club admin, and an operator with the staff flag but no platform authority: it isn't there.
    admin = make_user("amina@example.com")
    make_club(admin=admin)
    for user in (admin, make_user("ops@example.com", is_staff=True)):
        response = getattr(logged_in(user), method)(P + path, {}, format="json")
        assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_a_deactivated_super_admin_is_shut_out(root, root_user):
    assert root.get(P + "overview/").status_code == 200
    User.objects.filter(pk=root_user.pk).update(is_active=False)
    assert root.get(P + "overview/").status_code == 401


def test_me_says_who_is_a_platform_admin(root):
    assert root.get("/api/v1/auth/me/").json()["is_platform_admin"] is True
    assert logged_in(make_user("p@example.com")).get("/api/v1/auth/me/").json()["is_platform_admin"] is False
    staff_only = logged_in(make_user("ops@example.com", is_staff=True))
    assert staff_only.get("/api/v1/auth/me/").json()["is_platform_admin"] is False


def test_the_overview_counts_accounts_and_organizations(root):
    player = make_user("player@example.com")
    make_user("gone@example.com", is_active=False)
    User.objects.create_user(email="walk-in@guests.invalid", display_name="Walk In")  # a guest: no account
    make_club(admin=player)
    make_club("Nyali Hall", kind=Organization.Kind.FACILITY)
    data = root.get(P + "overview/").json()
    assert (data["accounts"], data["accounts_new"], data["accounts_inactive"]) == (3, 3, 1)
    assert data["platform_admins"] == 1
    assert data["organizations"]["club"] == 1 and data["organizations"]["facility"] == 1
    assert data["organizations"]["national_body"] == 0
    assert data["tournaments"]["draft"] == 0
    assert data["tournaments_awaiting_approval"] == 0 and data["events_awaiting_review"] == 0


def test_accounts_are_listed_newest_first_searched_and_filtered(root, root_user):
    amina = make_user("amina@coast.example", display_name="Amina Said", phone="+254712345678")
    make_user("baraka@coast.example", display_name="Baraka Otieno", is_active=False)
    User.objects.create_user(email="walk-in@guests.invalid", display_name="Amina Guest")
    make_club(admin=amina)

    rows = root.get(P + "accounts/").json()
    assert rows["count"] == 3
    assert [r["display_name"] for r in rows["results"]] == ["Baraka Otieno", "Amina Said", "Root Owner"]
    first = next(r for r in rows["results"] if r["id"] == str(amina.id))
    assert first["email"] == "amina@coast.example" and first["organizations"] == 1
    assert first["is_platform_admin"] is False and first["is_active"] is True
    assert "password" not in first

    def names(query):
        return [r["display_name"] for r in root.get(P + "accounts/" + query).json()["results"]]

    assert names("?search=amina") == ["Amina Said"]  # the guest of that name has no account
    assert names("?search=71234") == ["Amina Said"]
    assert names("?search=COAST.example") == ["Baraka Otieno", "Amina Said"]
    assert names("?show=inactive") == ["Baraka Otieno"]
    assert names("?show=admins") == ["Root Owner"]
    assert root.get(P + "accounts/?page_size=1").json()["next"]
    assert len(root.get(P + "accounts/?page_size=500").json()["results"]) == 3  # capped at 100 a page


def test_an_account_is_switched_off_and_cannot_sign_in_or_carry_on(root):
    player = make_user("player@example.com")
    theirs = logged_in(player)
    url = f"{P}accounts/{player.id}/"

    response = root.patch(url, {"is_active": False}, format="json")
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert theirs.get("/api/v1/auth/me/").status_code == 401  # the open session ends
    again = BrowserClient().post(
        "/api/v1/auth/login/", {"email": player.email, "password": PASSWORD}, format="json"
    )
    assert again.status_code == 400 and again.json()["code"] == "invalid_credentials"

    assert root.patch(url, {"is_active": True}, format="json").json()["is_active"] is True
    assert logged_in(player).get("/api/v1/auth/me/").status_code == 200


def test_platform_authority_is_given_and_taken(root):
    player = make_user("deputy@example.com")
    url = f"{P}accounts/{player.id}/"
    theirs = logged_in(player)
    assert theirs.get(P + "overview/").status_code == 404

    given = root.patch(url, {"is_platform_admin": True}, format="json")
    assert given.status_code == 200 and given.json()["is_platform_admin"] is True
    player.refresh_from_db()
    assert player.is_superuser and player.is_staff
    assert theirs.get(P + "overview/").status_code == 200

    taken = root.patch(url, {"is_platform_admin": False}, format="json")
    assert taken.json()["is_platform_admin"] is False
    player.refresh_from_db()
    assert not player.is_superuser and not player.is_staff
    assert theirs.get(P + "overview/").status_code == 404


def test_nobody_changes_their_own_account_so_one_super_admin_always_remains(root, root_user):
    url = f"{P}accounts/{root_user.id}/"
    for change in ({"is_platform_admin": False}, {"is_active": False}):
        response = root.patch(url, change, format="json")
        assert response.status_code == 409 and response.json()["code"] == "own_account"
    root_user.refresh_from_db()
    assert root_user.is_superuser and root_user.is_active


def test_account_changes_are_checked(root):
    unverified = User.objects.create_user(email="new@example.com", password=PASSWORD, display_name="New")
    refused = root.patch(f"{P}accounts/{unverified.id}/", {"is_platform_admin": True}, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "account_not_ready"

    player = make_user("player@example.com")
    url = f"{P}accounts/{player.id}/"
    assert root.patch(url, {}, format="json").status_code == 400
    assert root.patch(url, {"is_active": "perhaps"}, format="json").status_code == 400
    # Nothing but the two switches: not the email, the password or the flags by their own names.
    for extra in ({"email": "mine@example.com"}, {"is_superuser": True}, {"password": "x" * 12}):
        answer = root.patch(url, {"is_active": True, **extra}, format="json")
        assert answer.status_code == 400 and set(answer.json()["fields"]) == set(extra)
    player.refresh_from_db()
    assert player.email == "player@example.com" and not player.is_superuser

    guest = User.objects.create_user(email="walk-in@guests.invalid", display_name="Walk In")
    assert root.patch(f"{P}accounts/{guest.id}/", {"is_active": False}, format="json").status_code == 404
    missing = "00000000-0000-4000-8000-000000000000"
    assert root.patch(f"{P}accounts/{missing}/", {"is_active": False}, format="json").status_code == 404


def test_organizations_are_listed_with_their_admin_and_members(root):
    amina = make_user("amina@example.com", display_name="Amina Said")
    club = make_club(admin=amina, country="KE", region="Mombasa")
    Membership.objects.create(organization=club, user=make_user("b@example.com"))
    Membership.objects.create(
        organization=club, user=make_user("left@example.com"), status=Membership.Status.LEFT
    )
    make_club("Nyali Hall", kind=Organization.Kind.FACILITY, town="Nyali")

    rows = root.get(P + "organizations/").json()["results"]
    assert [(r["name"], r["members"], r["admin_name"]) for r in rows] == [
        ("Coast Spinners", 2, "Amina Said"),
        ("Nyali Hall", 0, None),
    ]
    assert rows[0]["country"] == "KE" and rows[0]["region"] == "Mombasa"

    def names(query):
        return [r["name"] for r in root.get(P + "organizations/" + query).json()["results"]]

    assert names("?search=nyali") == ["Nyali Hall"]
    assert names("?search=mombasa") == ["Coast Spinners"]
    assert names("?kind=facility") == ["Nyali Hall"]
    assert names("?kind=nonsense") == ["Coast Spinners", "Nyali Hall"]


def test_listing_accounts_and_organizations_takes_a_fixed_number_of_queries(
    root, django_assert_max_num_queries
):
    for n in range(6):
        user = make_user(f"p{n}@example.com")
        make_club(f"Club {n}", admin=user)
    with django_assert_max_num_queries(6):
        assert root.get(P + "accounts/").json()["count"] == 7
    with django_assert_max_num_queries(6):
        assert root.get(P + "organizations/").json()["count"] == 6


def test_the_catalogue_is_read_and_a_country_switched_to_listed_places_only(root, kenya):
    data = root.get(P + "countries/ke/").json()
    region = next(r for r in data["regions"] if r["id"] == kenya["region"].id)
    assert region == {
        "id": kenya["region"].id,
        "name": "Pwani Test",
        "cities": [{"id": kenya["city"].id, "name": "Mtwapa"}],
    }
    assert root.get(P + "countries/ZZ/").status_code == 404

    before = data["catalogue_only"]
    changed = root.patch(P + "countries/KE/", {"catalogue_only": not before}, format="json")
    assert changed.status_code == 200 and changed.json()["catalogue_only"] is (not before)
    assert root.patch(P + "countries/KE/", {}, format="json").status_code == 400


def test_regions_and_towns_are_added_once(root, kenya):
    added = root.post(P + "countries/KE/regions/", {"name": "  Lamu   Test "}, format="json")
    assert added.status_code == 201 and added.json()["name"] == "Lamu Test"
    twice = root.post(P + "countries/KE/regions/", {"name": "lamu test"}, format="json")
    assert twice.status_code == 409 and twice.json()["code"] == "place_exists"

    towns = f"{P}regions/{added.json()['id']}/cities/"
    town = root.post(towns, {"name": "Shela"}, format="json")
    assert town.status_code == 201 and town.json()["name"] == "Shela"
    assert root.post(towns, {"name": "SHELA"}, format="json").status_code == 409

    for bad in ({}, {"name": ""}, {"name": "x"}, {"name": "y" * 101}):
        assert root.post(P + "countries/KE/regions/", bad, format="json").status_code == 400
    assert root.post(f"{P}regions/999999/cities/", {"name": "Nowhere"}, format="json").status_code == 404


def test_renaming_a_place_takes_its_clubs_and_players_along(root, kenya):
    club = make_club(country="KE", region="Pwani Test", town="Mtwapa")
    elsewhere = make_club("Other", country="KE", region="Mombasa", town="Mtwapa")
    player = make_user("player@example.com")
    PlayerProfile.objects.update_or_create(
        user=player, defaults={"country": "KE", "region": "Pwani Test", "city": "Mtwapa"}
    )

    town = root.patch(f"{P}cities/{kenya['city'].id}/", {"name": "Mtwapa Creek"}, format="json")
    assert town.status_code == 200 and town.json()["name"] == "Mtwapa Creek"
    region = root.patch(f"{P}regions/{kenya['region'].id}/", {"name": "Pwani North"}, format="json")
    assert region.status_code == 200 and region.json()["name"] == "Pwani North"

    club.refresh_from_db()
    elsewhere.refresh_from_db()
    profile = PlayerProfile.objects.get(user=player)
    assert (club.region, club.town) == ("Pwani North", "Mtwapa Creek")
    assert (profile.region, profile.city) == ("Pwani North", "Mtwapa Creek")
    assert (elsewhere.region, elsewhere.town) == ("Mombasa", "Mtwapa")  # another region's town of that name

    other = Region.objects.create(country=kenya["country"], name="Tana Test")
    clash = root.patch(f"{P}regions/{other.id}/", {"name": "pwani north"}, format="json")
    assert clash.status_code == 409 and clash.json()["code"] == "place_exists"
    other.refresh_from_db()
    assert other.name == "Tana Test"


def test_a_place_in_use_is_not_removed(root, kenya):
    make_club(country="KE", region="Pwani Test", town="Mtwapa")
    city, region = f"{P}cities/{kenya['city'].id}/", f"{P}regions/{kenya['region'].id}/"
    for url in (city, region):
        response = root.delete(url)
        assert response.status_code == 409 and response.json()["code"] == "place_in_use"

    Organization.objects.all().delete()
    assert root.delete(region).status_code == 409  # its town is still listed
    assert root.delete(city).status_code == 204
    assert root.delete(region).status_code == 204
    assert not Region.objects.filter(pk=kenya["region"].id).exists()
    assert root.delete(region).status_code == 404


def test_changes_are_written_to_the_log_with_who_made_them(root, root_user, caplog):
    player = make_user("player@example.com")
    with caplog.at_level("INFO", logger="backoffice.views"):
        root.patch(f"{P}accounts/{player.id}/", {"is_active": False}, format="json")
    entry = next(r for r in caplog.records if r.getMessage() == "platform.account_changed")
    assert entry.actor == str(root_user.id) and entry.account == str(player.id) and entry.is_active is False
    assert player.email not in caplog.text
