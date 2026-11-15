from datetime import timedelta

import pytest
from django.utils import timezone

from organizations.models import Invitation, JoinRequest, Membership, Organization

from .conftest import BrowserClient
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
        logged_in(admin).get("/api/v1/me/memberships/").json()["results"][0]["organization"]["name"]
        == "Coast TT Club"
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
    pending = admin_client.get(requests_url(club)).json()["results"]
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
    assert [
        m["organization"]["id"] for m in player_client.get("/api/v1/me/memberships/").json()["results"]
    ] == [str(club.id)]


def test_rejected_player_may_ask_again(admin, player, club):
    player_client = logged_in(player)
    first = player_client.post(requests_url(club), {}, format="json").json()["id"]
    logged_in(admin).post(f"{requests_url(club)}{first}/reject/", {}, format="json")
    assert not Membership.objects.filter(organization=club, user=player).exists()
    second = player_client.post(requests_url(club), {}, format="json")
    assert second.status_code == 201 and second.json()["id"] != first
    mine = player_client.get("/api/v1/me/join-requests/").json()["results"]
    assert [(r["status"], r["organization"]["name"]) for r in mine] == [
        ("pending", club.name),
        ("rejected", club.name),
    ]


def test_outsider_and_requester_cannot_manage_requests(admin, player, club):
    """EVAL-004: an outsider cannot approve their own request."""
    player_client = logged_in(player)
    request_id = player_client.post(requests_url(club), {}, format="json").json()["id"]
    denied = player_client.get(requests_url(club))
    assert denied.status_code == 403 and denied.json()["code"] == "not_organization_admin"
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
    names = {
        m["organization"]["name"] for m in logged_in(admin).get("/api/v1/me/memberships/").json()["results"]
    }
    assert names == {"Coast TT Club", "Second Club"}


def test_returning_former_admin_rejoins_as_member(admin, player, club):
    """Approval grants membership only; a former admin's old role is not restored."""
    Membership.objects.create(organization=club, user=player, role="admin", status="left")
    request_id = logged_in(player).post(requests_url(club), {}, format="json").json()["id"]
    logged_in(admin).post(f"{requests_url(club)}{request_id}/approve/", {}, format="json")
    membership = Membership.objects.get(organization=club, user=player)
    assert (membership.role, membership.status) == ("member", "active")


# Invitations (REQ-004: invited members explicitly accept)


def invitations_url(org):
    return f"{ORGS}{org.id}/invitations/"


MY_INVITATIONS = "/api/v1/me/invitations/"


def test_invite_accept_flow(admin, player, club, mailoutbox):
    staff = logged_in(admin)
    response = staff.post(invitations_url(club), {"email": " Player@Example.com "}, format="json")
    assert response.status_code == 201, response.json()
    invitation = response.json()
    assert invitation["email"] == "player@example.com" and invitation["status"] == "pending"
    assert mailoutbox[-1].to == ["player@example.com"] and "/club/invitations" in mailoutbox[-1].body

    # Nothing is joined until the invitee accepts.
    assert not Membership.objects.filter(organization=club, user=player).exists()
    invitee = logged_in(player)
    mine = invitee.get(MY_INVITATIONS).json()["results"]
    assert [(i["id"], i["organization"]["name"], i["invited_by_name"]) for i in mine] == [
        (invitation["id"], "Coast TT Club", "Club Admin")
    ]
    accepted = invitee.post(f"{MY_INVITATIONS}{invitation['id']}/accept/")
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    membership = Membership.objects.get(organization=club, user=player)
    assert (membership.role, membership.status) == ("member", "active")
    assert invitee.get(MY_INVITATIONS).json()["results"] == []
    assert invitee.post(f"{MY_INVITATIONS}{invitation['id']}/accept/").status_code == 404


def test_decline_creates_no_membership(admin, player, club):
    invitation = logged_in(admin).post(invitations_url(club), {"email": player.email}, format="json").json()
    response = logged_in(player).post(f"{MY_INVITATIONS}{invitation['id']}/decline/")
    assert response.json()["status"] == "declined"
    assert not Membership.objects.filter(organization=club, user=player).exists()


def test_only_the_addressee_sees_or_answers(admin, player, club):
    invitation = logged_in(admin).post(invitations_url(club), {"email": player.email}, format="json").json()
    other = logged_in(make_user("other@example.com"))
    assert other.get(MY_INVITATIONS).json()["results"] == []
    assert other.post(f"{MY_INVITATIONS}{invitation['id']}/accept/").status_code == 404

    player.email_verified_at = None  # an unverified address proves nothing
    player.save()
    client = BrowserClient()
    client.force_login(player)
    assert client.get(MY_INVITATIONS).json()["results"] == []


def test_only_admins_manage_invitations(player, club):
    outsider = logged_in(player)
    assert outsider.post(invitations_url(club), {"email": "x@example.com"}, format="json").status_code == 403
    assert outsider.get(invitations_url(club)).status_code == 403


def test_inviting_is_idempotent_and_never_reveals_accounts(admin, club, mailoutbox):
    staff = logged_in(admin)
    unknown = staff.post(invitations_url(club), {"email": "nobody@example.com"}, format="json")
    assert unknown.status_code == 201  # same reply as for a registered address
    again = staff.post(invitations_url(club), {"email": "nobody@example.com"}, format="json")
    assert again.status_code == 200 and again.json()["id"] == unknown.json()["id"]
    assert len(mailoutbox) == 2  # re-inviting resends the email
    assert [i["email"] for i in staff.get(invitations_url(club)).json()["results"]] == ["nobody@example.com"]


def test_inviting_a_member_reveals_nothing(admin, player, club):
    """The reply for a member's address matches any other, so admins can't probe who has which email."""
    Membership.objects.create(organization=club, user=player)
    response = logged_in(admin).post(invitations_url(club), {"email": player.email}, format="json")
    assert response.status_code == 201
    logged_in(player).post(f"{MY_INVITATIONS}{response.json()['id']}/accept/")
    assert Membership.objects.get(organization=club, user=player).role == "member"


def test_admin_of_another_org_cannot_touch_invitations(admin, player, club):
    """EVAL-004: authority is per organization."""
    invitation = logged_in(admin).post(invitations_url(club), {"email": player.email}, format="json").json()
    other_admin = make_user("other@example.com")
    other = logged_in(other_admin)
    other.post(ORGS, {"name": "Other Club", "town": "Kilifi", "kind": "club"}, format="json")
    assert other.get(invitations_url(club)).status_code == 403
    assert other.post(invitations_url(club), {"email": "x@example.com"}, format="json").status_code == 403
    assert other.post(f"{invitations_url(club)}{invitation['id']}/revoke/").status_code == 403
    assert Invitation.objects.get(pk=invitation["id"]).status == "pending"


def test_lapsed_invitations_are_not_listed_as_pending(admin, club):
    staff = logged_in(admin)
    invitation = staff.post(invitations_url(club), {"email": "late@example.com"}, format="json").json()
    Invitation.objects.filter(pk=invitation["id"]).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert staff.get(invitations_url(club)).json()["results"] == []


def test_sending_invitations_is_throttled(admin, club, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle

    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "invitations", "2/hour")
    staff = logged_in(admin)
    codes = [
        staff.post(invitations_url(club), {"email": f"p{i}@example.com"}, format="json").status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]
    assert staff.get(invitations_url(club)).status_code == 200  # listing isn't limited


def test_email_is_stored_lower_cased(club):
    assert (
        Invitation.objects.create(organization=club, email=" Mixed@Example.COM ").email == "mixed@example.com"
    )


def test_revoked_and_expired_invitations_cannot_be_accepted(admin, player, club):
    staff = logged_in(admin)
    invitation = staff.post(invitations_url(club), {"email": player.email}, format="json").json()
    assert staff.post(f"{invitations_url(club)}{invitation['id']}/revoke/").json()["status"] == "revoked"
    assert staff.post(f"{invitations_url(club)}{invitation['id']}/revoke/").status_code == 409
    invitee = logged_in(player)
    assert invitee.post(f"{MY_INVITATIONS}{invitation['id']}/accept/").status_code == 404

    renewed = staff.post(invitations_url(club), {"email": player.email}, format="json").json()
    Invitation.objects.filter(pk=renewed["id"]).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert invitee.post(f"{MY_INVITATIONS}{renewed['id']}/accept/").status_code == 404
    # Inviting again renews the lapsed invitation instead of failing on the pending one.
    again = staff.post(invitations_url(club), {"email": player.email}, format="json").json()
    assert again["id"] == renewed["id"]
    assert invitee.post(f"{MY_INVITATIONS}{renewed['id']}/accept/").status_code == 200


def test_accepting_withdraws_an_open_join_request_and_keeps_admin_role(admin, player, club):
    invitee = logged_in(player)
    invitee.post(requests_url(club))
    invitation = logged_in(admin).post(invitations_url(club), {"email": player.email}, format="json").json()
    invitee.post(f"{MY_INVITATIONS}{invitation['id']}/accept/")
    join_request = JoinRequest.objects.get(organization=club, user=player)
    # Withdrawn rather than approved: no admin decided it, so none is recorded.
    assert (join_request.status, join_request.decided_by) == ("withdrawn", None)
    assert logged_in(admin).get(requests_url(club)).json()["results"] == []

    # Accepting a stray invitation never demotes an existing admin.
    Invitation.objects.create(organization=club, email=admin.email)
    stray = Invitation.objects.get(organization=club, email=admin.email)
    logged_in(admin).post(f"{MY_INVITATIONS}{stray.id}/accept/")
    assert Membership.objects.get(organization=club, user=admin).role == "admin"
