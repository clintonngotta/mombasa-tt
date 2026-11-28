"""Staff invite a player found in the player directory to their club or team (REQ-004, REQ-057). The
player still accepts; staff never see the player's email; only listed players can be invited this way."""

import pytest

from organizations.models import Invitation, Membership
from profiles.models import profile_for

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_organizations import MY_INVITATIONS, ORGS, admin, club, invitations_url, player  # noqa: F401

pytestmark = pytest.mark.django_db


def listed(user):
    profile = profile_for(user)
    profile.directory_opt_in = True
    profile.save()
    return user


@pytest.fixture
def team(admin):  # noqa: F811
    response = logged_in(admin).post(
        ORGS, {"name": "Coast Loopas Team", "town": "Mombasa", "kind": "team"}, format="json"
    )
    assert response.status_code == 201, response.json()
    return response.json()


def test_a_listed_player_is_invited_and_accepts(admin, player, team, mailoutbox):  # noqa: F811
    listed(player)
    url = f"{ORGS}{team['id']}/invitations/"
    sent = logged_in(admin).post(url, {"player_id": str(player.id)}, format="json")
    assert sent.status_code == 201, sent.json()
    assert sent.json()["invitee_name"] == "Player One" and sent.json()["email"] == ""
    # Staff see the name, never the player's address.
    assert "player@example.com" not in str(logged_in(admin).get(url).json())
    assert mailoutbox[-1].to == ["player@example.com"]

    invitee = logged_in(player)
    mine = invitee.get(MY_INVITATIONS).json()["results"]
    assert [i["organization"]["name"] for i in mine] == ["Coast Loopas Team"]
    assert not Membership.objects.filter(organization_id=team["id"], user=player).exists()
    assert invitee.post(f"{MY_INVITATIONS}{mine[0]['id']}/accept/").status_code == 200
    assert Membership.objects.active().filter(organization_id=team["id"], user=player).exists()


def test_inviting_the_same_player_twice_keeps_one_invitation(admin, player, club):  # noqa: F811
    listed(player)
    staff = logged_in(admin)
    first = staff.post(invitations_url(club), {"player_id": str(player.id)}, format="json")
    again = staff.post(invitations_url(club), {"player_id": str(player.id)}, format="json")
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert Invitation.objects.filter(organization=club, invitee=player).count() == 1


def test_only_listed_active_players_can_be_invited(admin, player, club):  # noqa: F811
    staff = logged_in(admin)
    unlisted = staff.post(invitations_url(club), {"player_id": str(player.id)}, format="json")
    assert unlisted.status_code == 400 and "player_id" in unlisted.json()["fields"]
    listed(player)
    player.is_active = False
    player.save()
    gone = staff.post(invitations_url(club), {"player_id": str(player.id)}, format="json")
    assert gone.status_code == 400
    nobody = {"player_id": "00000000-0000-0000-0000-000000000000"}
    assert staff.post(invitations_url(club), nobody, format="json").status_code == 400


def test_a_member_is_not_invited_again(admin, club):  # noqa: F811
    listed(admin)
    answer = logged_in(admin).post(invitations_url(club), {"player_id": str(admin.id)}, format="json")
    assert answer.status_code == 409 and answer.json()["code"] == "already_member"


def test_one_of_email_or_player(admin, player, club):  # noqa: F811
    listed(player)
    staff = logged_in(admin)
    body = {"email": "a@example.com", "player_id": str(player.id)}
    both = staff.post(invitations_url(club), body, format="json")
    neither = staff.post(invitations_url(club), {}, format="json")
    assert both.status_code == 400 and neither.status_code == 400


def test_only_the_invited_player_sees_or_answers(admin, player, club):  # noqa: F811
    listed(player)
    sent = logged_in(admin).post(invitations_url(club), {"player_id": str(player.id)}, format="json").json()
    other = logged_in(make_user("other@example.com"))
    assert other.get(MY_INVITATIONS).json()["results"] == []
    assert other.post(f"{MY_INVITATIONS}{sent['id']}/accept/").status_code == 404


def test_a_player_without_a_verified_email_still_gets_it_in_the_app(admin, club, mailoutbox):  # noqa: F811
    phone_only = listed(make_user("phone@example.com", display_name="Phone Only"))
    phone_only.email_verified_at = None
    phone_only.save()
    before = len(mailoutbox)
    sent = logged_in(admin).post(invitations_url(club), {"player_id": str(phone_only.id)}, format="json")
    assert sent.status_code == 201 and len(mailoutbox) == before
    client = BrowserClient()
    client.force_login(phone_only)  # no verified address to log in with a password
    assert [i["id"] for i in client.get(MY_INVITATIONS).json()["results"]] == [sent.json()["id"]]


def test_only_member_managers_invite_players(player, club):  # noqa: F811
    listed(player)
    outsider = logged_in(make_user("outsider@example.com"))
    refused = outsider.post(invitations_url(club), {"player_id": str(player.id)}, format="json")
    assert refused.status_code == 403
