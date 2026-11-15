import pytest

from organizations.models import JoinRequest, Membership, Organization

from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db
ORGS = "/api/v1/organizations/"


@pytest.fixture
def admin(db):
    return make_user("admin@example.com", display_name="Club Admin")


@pytest.fixture
def player(db):
    return make_user("player@example.com", display_name="Player One")


@pytest.fixture
def club(admin):
    response = logged_in(admin).post(
        ORGS, {"name": "Coast TT Club", "town": "Mombasa", "kind": "club_facility"}, format="json"
    )
    assert response.status_code == 201, response.json()
    return Organization.objects.get(pk=response.json()["id"])


def requests_url(org):
    return f"{ORGS}{org.id}/join-requests/"


def test_creator_becomes_first_admin(admin, club):
    membership = Membership.objects.get(organization=club)
    assert (membership.user, membership.role, membership.status) == (admin, "admin", "active")
    assert (
        logged_in(admin).get("/api/v1/me/memberships/").json()[0]["organization"]["name"] == "Coast TT Club"
    )


def test_create_validation(admin):
    response = logged_in(admin).post(ORGS, {"name": "  ", "town": "Mombasa", "kind": "league"}, format="json")
    assert response.status_code == 400
    assert set(response.json()["fields"]) == {"name", "kind"}


def test_search_by_name_or_town(player, club):
    Organization.objects.create(name="Nairobi Spin", town="Nairobi", kind="club")
    client = logged_in(player)
    assert [o["name"] for o in client.get(f"{ORGS}?search=mombasa").json()["results"]] == ["Coast TT Club"]
    assert [o["name"] for o in client.get(f"{ORGS}?search=spin").json()["results"]] == ["Nairobi Spin"]
    assert client.get(f"{ORGS}?search=coast").json()["results"][0] == {
        "id": str(club.id),
        "name": "Coast TT Club",
        "town": "Mombasa",
        "kind": "club_facility",
    }


def test_join_request_approve_flow(admin, player, club):
    player_client = logged_in(player)
    response = player_client.post(requests_url(club), {}, format="json")
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    # Asking again returns the same open request.
    again = player_client.post(requests_url(club), {}, format="json")
    assert again.status_code == 200 and again.json()["id"] == response.json()["id"]

    admin_client = logged_in(admin)
    pending = admin_client.get(requests_url(club)).json()
    assert [(r["display_name"], r["status"]) for r in pending] == [("Player One", "pending")]
    assert "email" not in pending[0]

    request_id = pending[0]["id"]
    approved = admin_client.post(f"{requests_url(club)}{request_id}/approve/", {}, format="json")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert Membership.objects.get(organization=club, user=player).role == "member"
    # Deciding twice is refused; joining again is refused.
    twice = admin_client.post(f"{requests_url(club)}{request_id}/reject/", {}, format="json")
    assert twice.status_code == 409 and twice.json()["code"] == "already_decided"
    assert player_client.post(requests_url(club), {}, format="json").json()["code"] == "already_member"
    assert [m["organization"]["id"] for m in player_client.get("/api/v1/me/memberships/").json()] == [
        str(club.id)
    ]


def test_rejected_player_may_ask_again(admin, player, club):
    player_client = logged_in(player)
    first = player_client.post(requests_url(club), {}, format="json").json()["id"]
    logged_in(admin).post(f"{requests_url(club)}{first}/reject/", {}, format="json")
    assert not Membership.objects.filter(organization=club, user=player).exists()
    second = player_client.post(requests_url(club), {}, format="json")
    assert second.status_code == 201 and second.json()["id"] != first
    statuses = [r["status"] for r in player_client.get("/api/v1/me/join-requests/").json()]
    assert statuses == ["pending", "rejected"]


def test_outsider_and_requester_cannot_manage_requests(admin, player, club):
    """EVAL-004: an outsider cannot approve their own request."""
    player_client = logged_in(player)
    request_id = player_client.post(requests_url(club), {}, format="json").json()["id"]
    assert player_client.get(requests_url(club)).status_code == 403
    assert (
        player_client.post(f"{requests_url(club)}{request_id}/approve/", {}, format="json").status_code == 403
    )

    # An admin of a different organization has no authority here.
    other_admin = make_user("other@example.com")
    other_client = logged_in(other_admin)
    other_client.post(ORGS, {"name": "Other Club", "town": "Kilifi", "kind": "club"}, format="json")
    assert (
        other_client.post(f"{requests_url(club)}{request_id}/approve/", {}, format="json").status_code == 403
    )
    assert JoinRequest.objects.get(pk=request_id).status == "pending"


def test_member_but_not_admin_cannot_approve(admin, player, club):
    Membership.objects.create(organization=club, user=player)
    applicant = make_user("new@example.com")
    request_id = logged_in(applicant).post(requests_url(club), {}, format="json").json()["id"]
    response = logged_in(player).post(f"{requests_url(club)}{request_id}/approve/", {}, format="json")
    assert response.status_code == 403


def test_request_from_another_org_is_not_found(admin, player, club):
    other = Organization.objects.create(name="Other", town="Kilifi")
    stray = JoinRequest.objects.create(organization=other, user=player)
    response = logged_in(admin).post(f"{requests_url(club)}{stray.id}/approve/", {}, format="json")
    assert response.status_code == 404


def test_players_can_belong_to_several_organizations(admin, player, club):
    second = Organization.objects.create(name="Second Club", town="Malindi")
    Membership.objects.create(organization=second, user=admin)
    names = {m["organization"]["name"] for m in logged_in(admin).get("/api/v1/me/memberships/").json()}
    assert names == {"Coast TT Club", "Second Club"}
