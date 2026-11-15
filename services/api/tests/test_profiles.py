import pytest

from organizations.models import Membership, Organization
from profiles.models import PlayerProfile

from .conftest import BrowserClient
from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db
PROFILE = "/api/v1/me/profile/"


@pytest.fixture
def ama(db):
    return make_user("ama@example.com", display_name="Ama Wanjiru")


def test_profile_requires_login():
    assert BrowserClient().get(PROFILE).status_code in {401, 403}


def test_new_profile_is_private_by_default(ama):
    data = logged_in(ama).get(PROFILE).json()
    assert data["display_name"] == "Ama Wanjiru"
    assert data["directory_opt_in"] is False
    assert data["published_details"] == []
    assert data["goals"] == []
    assert data["onboarding_completed"] is False


def test_patch_updates_profile_and_display_name(ama):
    client = logged_in(ama)
    response = client.patch(
        PROFILE,
        {
            "display_name": "  Ama W.  ",
            "nickname": "Flick",
            "hand": "left",
            "grip": "penhold",
            "style": "Offensive looper",
            "experience": "club",
            "bio": "Weekend league player.",
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    ama.refresh_from_db()
    assert ama.display_name == "Ama W."
    assert response.json()["hand"] == "left"
    # The onboarding form sends empty strings for skipped choices.
    assert client.patch(PROFILE, {"hand": "", "grip": ""}, format="json").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"display_name": "   "},
        {"hand": "both"},
        {"bio": "x" * 281},
        {"experience": "pro"},
        {"published_details": ["email"]},
    ],
)
def test_patch_validation(ama, body):
    response = logged_in(ama).patch(PROFILE, body, format="json")
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert set(response.json()["fields"]) == set(body)


def test_goals_are_replaced_and_do_not_grant_roles(ama):
    client = logged_in(ama)
    response = client.put("/api/v1/me/goals/", {"goals": ["organize", "umpire", "organize"]}, format="json")
    assert response.status_code == 200
    assert response.json()["goals"] == ["organize", "umpire"]
    assert not Membership.objects.filter(user=ama).exists()
    assert client.put("/api/v1/me/goals/", {"goals": ["admin"]}, format="json").status_code == 400
    assert client.put("/api/v1/me/goals/", {"goals": []}, format="json").json()["goals"] == []


def test_goals_cannot_be_set_through_profile_patch(ama):
    logged_in(ama).patch(PROFILE, {"goals": ["organize"]}, format="json")
    assert PlayerProfile.objects.get(user=ama).goals == []


def test_complete_onboarding_is_idempotent(ama):
    client = logged_in(ama)
    assert client.post("/api/v1/me/onboarding/complete/", {}, format="json").status_code == 204
    first = PlayerProfile.objects.get(user=ama).onboarding_completed_at
    assert client.post("/api/v1/me/onboarding/complete/", {}, format="json").status_code == 204
    assert PlayerProfile.objects.get(user=ama).onboarding_completed_at == first
    assert client.get(PROFILE).json()["onboarding_completed"] is True


def test_directory_lists_only_opted_in_players_without_private_fields(ama):
    listed = make_user("baraka@example.com", display_name="Baraka Otieno")
    hidden = make_user("bakari@example.com", display_name="Bakari Hidden")
    PlayerProfile.objects.create(user=listed, directory_opt_in=True, nickname="Bara", bio="private bio")
    PlayerProfile.objects.create(user=hidden, directory_opt_in=False)
    club = Organization.objects.create(name="Coast TT Club", town="Mombasa")
    Membership.objects.create(organization=club, user=listed)

    client = logged_in(ama)
    results = client.get("/api/v1/players/?search=ba").json()["results"]
    assert results == [
        {
            "id": str(listed.id),
            "display_name": "Baraka Otieno",
            "nickname": "Bara",
            "clubs": ["Coast TT Club"],
        }
    ]
    # Too-short queries return nothing rather than the whole directory.
    assert client.get("/api/v1/players/?search=b").json()["results"] == []
    assert client.get("/api/v1/players/").json()["results"] == []


def test_opting_out_removes_player_from_directory(ama):
    client = logged_in(ama)
    client.patch(PROFILE, {"directory_opt_in": True}, format="json")
    other = logged_in(make_user("zawadi@example.com"))
    assert len(other.get("/api/v1/players/?search=Ama").json()["results"]) == 1
    client.patch(PROFILE, {"directory_opt_in": False}, format="json")
    assert other.get("/api/v1/players/?search=Ama").json()["results"] == []


def test_blank_display_name_gets_friendly_message(ama):
    response = logged_in(ama).patch(PROFILE, {"display_name": "  "}, format="json")
    assert response.json()["fields"]["display_name"] == "Enter the name other players will see."


def player_url(user):
    return f"/api/v1/players/{user.id}/"


def test_player_page_shows_only_published_details(ama):
    PlayerProfile.objects.create(
        user=ama,
        directory_opt_in=True,
        nickname="Flick",
        hand="left",
        grip="penhold",
        style="Looper",
        bio="Private until published",
        published_details=["hand", "style", "experience"],  # experience is blank, so stays null
    )
    data = logged_in(make_user("zawadi@example.com")).get(player_url(ama)).json()
    assert data == {
        "id": str(ama.id),
        "display_name": "Ama Wanjiru",
        "nickname": "Flick",
        "clubs": [],
        "hand": "left",
        "grip": None,
        "style": "Looper",
        "experience": None,
        "bio": None,
    }
    assert "email" not in data


def test_player_page_disappears_when_opted_out(ama):
    client = logged_in(ama)
    client.patch(PROFILE, {"directory_opt_in": True, "published_details": ["bio", "bio"]}, format="json")
    assert client.get(PROFILE).json()["published_details"] == ["bio"]
    other = logged_in(make_user("zawadi@example.com"))
    assert other.get(player_url(ama)).status_code == 200
    client.patch(PROFILE, {"directory_opt_in": False}, format="json")
    assert other.get(player_url(ama)).status_code == 404


def test_player_page_requires_login(ama):
    PlayerProfile.objects.create(user=ama, directory_opt_in=True)
    assert BrowserClient().get(player_url(ama)).status_code in {401, 403}


def test_player_page_with_nothing_published_shows_only_directory_fields(ama):
    PlayerProfile.objects.create(
        user=ama,
        directory_opt_in=True,
        hand="right",
        grip="shakehand",
        style="Chopper",
        experience="club",
        bio="Hi",
    )
    data = logged_in(make_user("zawadi@example.com")).get(player_url(ama)).json()
    assert {k: v for k, v in data.items() if v is not None} == {
        "id": str(ama.id),
        "display_name": "Ama Wanjiru",
        "nickname": "",
        "clubs": [],
    }


def test_player_page_hides_deactivated_players(ama):
    PlayerProfile.objects.create(user=ama, directory_opt_in=True)
    ama.is_active = False
    ama.save(update_fields=["is_active"])
    assert logged_in(make_user("zawadi@example.com")).get(player_url(ama)).status_code == 404
