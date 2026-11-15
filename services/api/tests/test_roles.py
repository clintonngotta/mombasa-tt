"""Permission catalog, role templates/editor and grant restrictions (REQ-005, EVAL-005, TASK-013)."""

import threading

import pytest
from django.db import connection

from organizations.models import Membership, Organization, Role
from organizations.permissions import ALL_PERMISSIONS

from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db
ORGS = "/api/v1/organizations/"
MEMBERSHIPS = "/api/v1/me/memberships/"


def create_club(owner, name="Coast TT Club") -> Organization:
    response = logged_in(owner).post(ORGS, {"name": name, "town": "Mombasa", "kind": "club"}, format="json")
    assert response.status_code == 201, response.json()
    return Organization.objects.get(pk=response.json()["id"])


def add_member(org, user, *role_keys_or_roles) -> Membership:
    membership = Membership.objects.create(organization=org, user=user)
    for role in role_keys_or_roles:
        membership.roles.add(role if isinstance(role, Role) else org.roles.get(key=role))
    return membership


def roles_url(org, role=None):
    return f"{ORGS}{org.id}/roles/" + (f"{role.id}/" if role else "")


def member_roles_url(org, membership):
    return f"{ORGS}{org.id}/members/{membership.id}/roles/"


def my_permissions(client, org) -> list[str]:
    for membership in client.get(MEMBERSHIPS).json()["results"]:
        if membership["organization"]["id"] == str(org.id):
            return membership["permissions"]
    return []


@pytest.fixture
def admin(db):
    return make_user("admin@example.com", display_name="Club Admin")


@pytest.fixture
def club(admin):
    return create_club(admin)


def code(response) -> str:
    return response.json()["code"]


def test_new_organization_gets_role_templates_and_admin_holds_everything(admin, club):
    assert sorted(club.roles.values_list("key", flat=True)) == [
        "admin",
        "assistant_captain",
        "captain",
        "committee",
        "member",
    ]
    client = logged_in(admin)
    mine = client.get(MEMBERSHIPS).json()["results"][0]
    assert [r["key"] for r in mine["roles"]] == ["admin"]
    assert set(mine["permissions"]) == ALL_PERMISSIONS

    roles = {r["key"]: r for r in client.get(roles_url(club)).json()}
    assert set(roles["admin"]["permissions"]) == ALL_PERMISSIONS
    assert roles["admin"]["member_count"] == 1 and roles["member"]["permissions"] == []


def test_permission_catalog_lists_every_permission(admin):
    catalog = logged_in(admin).get(f"{ORGS}permissions/").json()
    assert {p["code"] for p in catalog} == ALL_PERMISSIONS
    assert all(p["label"] for p in catalog)


def test_permissions_gate_member_management(admin, club):
    captain, committee, plain = (make_user(f"{n}@example.com") for n in ("captain", "committee", "plain"))
    add_member(club, captain, "captain")
    add_member(club, committee, "committee")
    add_member(club, plain)
    requests = f"{ORGS}{club.id}/join-requests/"
    invitations = f"{ORGS}{club.id}/invitations/"

    assert logged_in(captain).get(requests).status_code == 200
    assert (
        logged_in(captain).post(invitations, {"email": "new@example.com"}, format="json").status_code == 201
    )
    for user in (committee, plain):
        denied = logged_in(user).get(requests)
        assert denied.status_code == 403 and code(denied) == "permission_denied"
        assert logged_in(user).post(invitations, {"email": "x@example.com"}, format="json").status_code == 403
    # Managing members is not managing roles.
    assert logged_in(captain).post(roles_url(club), {"name": "Coach"}, format="json").status_code == 403
    assert logged_in(plain).get(roles_url(club)).status_code == 403
    assert logged_in(plain).get(f"{ORGS}{club.id}/members/").status_code == 403


def test_effective_permissions_are_the_union_of_roles_plus_member_role(admin, club):
    player = make_user("player@example.com")
    add_member(club, player, "committee", "assistant_captain")
    client = logged_in(player)
    committee = set(club.roles.get(key="committee").permissions)
    assistant = set(club.roles.get(key="assistant_captain").permissions)
    assert set(my_permissions(client, club)) == committee | assistant

    member_role = club.roles.get(key="member")
    response = logged_in(admin).patch(
        roles_url(club, member_role), {"permissions": ["activities.manage", "training.manage"]}, format="json"
    )
    assert response.status_code == 200
    assert {"activities.manage", "training.manage"} <= set(my_permissions(client, club))


def test_admin_creates_edits_and_deletes_custom_roles(admin, club):
    client = logged_in(admin)
    created = client.post(
        roles_url(club),
        {"name": " Treasurer ", "permissions": ["finances.manage", "finances.view"]},
        format="json",
    )
    assert created.status_code == 201
    body = created.json()
    assert (body["name"], body["key"], body["permissions"]) == (
        "Treasurer",
        "",
        ["finances.manage", "finances.view"],
    )

    duplicate = client.post(roles_url(club), {"name": "treasurer"}, format="json")
    assert duplicate.status_code == 400 and "name" in duplicate.json()["fields"]
    unknown = client.post(
        roles_url(club), {"name": "Ghost", "permissions": ["billing.manage"]}, format="json"
    )
    assert unknown.status_code == 400 and "permissions" in unknown.json()["fields"]

    treasurer = Role.objects.get(pk=body["id"])
    player = make_user("player@example.com")
    add_member(club, player, treasurer)
    renamed = client.patch(roles_url(club, treasurer), {"name": "Finance lead"}, format="json")
    assert renamed.status_code == 200 and renamed.json()["name"] == "Finance lead"

    assert client.delete(roles_url(club, treasurer)).status_code == 204
    assert not Membership.objects.get(user=player).roles.exists()


def test_admin_and_member_roles_are_protected(admin, club):
    client = logged_in(admin)
    admin_role, member_role = club.roles.get(key="admin"), club.roles.get(key="member")
    locked = client.patch(roles_url(club, admin_role), {"permissions": ["members.manage"]}, format="json")
    assert locked.status_code == 409 and code(locked) == "admin_role_locked"
    assert client.patch(roles_url(club, admin_role), {"name": "Chair"}, format="json").status_code == 200
    for role in (admin_role, member_role):
        refused = client.delete(roles_url(club, role))
        assert refused.status_code == 409 and code(refused) == "role_required"
    # The Member role applies to everyone and can't be assigned by hand.
    me = Membership.objects.get(user=admin)
    response = client.put(
        member_roles_url(club, me), {"roles": [str(admin_role.id), str(member_role.id)]}, format="json"
    )
    assert response.status_code == 400 and "roles" in response.json()["fields"]


def test_granting_never_exceeds_the_actors_own_permissions(admin, club):
    """EVAL-005: attempt wider grants than you hold."""
    manager_role = Role.objects.create(
        organization=club, name="Membership secretary", permissions=["members.manage", "roles.manage"]
    )
    secretary = make_user("secretary@example.com")
    target = make_user("target@example.com")
    mine = add_member(club, secretary, manager_role)
    theirs = add_member(club, target)
    client = logged_in(secretary)

    # Creating a role with a permission the secretary lacks.
    wider = client.post(roles_url(club), {"name": "Bank", "permissions": ["finances.manage"]}, format="json")
    assert wider.status_code == 403 and code(wider) == "beyond_your_authority"
    within = client.post(roles_url(club), {"name": "Door", "permissions": ["members.manage"]}, format="json")
    assert within.status_code == 201

    # Escalating themselves or others.
    for key in ("admin", "captain", "committee"):
        role = club.roles.get(key=key)
        assert (
            client.put(
                member_roles_url(club, mine), {"roles": [str(manager_role.id), str(role.id)]}, format="json"
            ).status_code
            == 403
        )
        assert (
            client.put(member_roles_url(club, theirs), {"roles": [str(role.id)]}, format="json").status_code
            == 403
        )
    door = Role.objects.get(pk=within.json()["id"])
    assert (
        client.put(member_roles_url(club, theirs), {"roles": [str(door.id)]}, format="json").status_code
        == 200
    )

    # Editing a role: adding or removing permissions they don't hold is refused; theirs is fine.
    committee = club.roles.get(key="committee")
    add = client.patch(
        roles_url(club, committee),
        {"permissions": [*committee.permissions, "facilities.manage"]},
        format="json",
    )
    assert add.status_code == 403
    drop = client.patch(roles_url(club, committee), {"permissions": ["activities.manage"]}, format="json")
    assert drop.status_code == 403
    ok = client.patch(
        roles_url(club, committee), {"permissions": [*committee.permissions, "members.manage"]}, format="json"
    )
    assert ok.status_code == 200 and "members.manage" in ok.json()["permissions"]
    # Deleting a role that carries permissions they lack.
    assert client.delete(roles_url(club, club.roles.get(key="captain"))).status_code == 403

    # Removing a member who holds more than they do.
    removal = logged_in(secretary).post(
        f"{ORGS}{club.id}/members/{Membership.objects.get(user=admin).id}/remove/"
    )
    assert removal.status_code == 403 and code(removal) == "beyond_your_authority"
    assert set(Membership.objects.get(user=secretary).roles.all()) == {manager_role}


def test_role_ids_from_another_organization_are_unknown(admin, club):
    """EVAL-005: cross-tenant role IDs cannot be used."""
    other_admin = make_user("other@example.com")
    other = create_club(other_admin, "Kilifi Spin")
    foreign_admin_role = other.roles.get(key="admin")
    player = make_user("player@example.com")
    membership = add_member(club, player)

    client = logged_in(admin)
    response = client.put(
        member_roles_url(club, membership), {"roles": [str(foreign_admin_role.id)]}, format="json"
    )
    assert response.status_code == 400 and "roles" in response.json()["fields"]
    assert (
        client.patch(roles_url(club, foreign_admin_role), {"name": "Mine"}, format="json").status_code == 404
    )
    assert client.delete(roles_url(club, other.roles.get(key="captain"))).status_code == 404
    # The other organization's admin has no authority here.
    outsider = logged_in(other_admin)
    assert outsider.get(roles_url(club)).status_code == 403
    assert outsider.put(member_roles_url(club, membership), {"roles": []}, format="json").status_code == 403
    assert not membership.roles.exists()


def test_last_admin_cannot_step_down_leave_or_be_removed(admin, club):
    client = logged_in(admin)
    me = Membership.objects.get(user=admin)
    step_down = client.put(member_roles_url(club, me), {"roles": []}, format="json")
    assert step_down.status_code == 409 and code(step_down) == "last_admin"
    leaving = client.post(f"{MEMBERSHIPS}{me.id}/leave/")
    assert leaving.status_code == 409 and code(leaving) == "last_admin"
    assert client.post(f"{ORGS}{club.id}/members/{me.id}/remove/").status_code == 409

    # With a second admin, either can step down.
    deputy = make_user("deputy@example.com")
    add_member(club, deputy, "admin")
    assert client.put(member_roles_url(club, me), {"roles": []}, format="json").status_code == 200
    assert Membership.objects.admins(club).get().user == deputy


def test_members_list_shows_names_and_roles_only(admin, club):
    player = make_user("player@example.com", display_name="Player One")
    add_member(club, player, "captain")
    results = logged_in(admin).get(f"{ORGS}{club.id}/members/?search=player").json()["results"]
    assert len(results) == 1
    assert set(results[0]) == {"id", "user", "display_name", "roles", "joined_at"}
    assert [r["key"] for r in results[0]["roles"]] == ["captain"]


def test_removed_or_departed_members_lose_roles_and_rejoin_without_them(admin, club):
    captain = make_user("captain@example.com")
    membership = add_member(club, captain, "captain")
    assert logged_in(admin).post(f"{ORGS}{club.id}/members/{membership.id}/remove/").status_code == 204
    membership.refresh_from_db()
    assert membership.status == "left" and not membership.roles.exists()
    assert logged_in(captain).get(f"{ORGS}{club.id}/join-requests/").status_code == 403

    player = make_user("player@example.com")
    mine = add_member(club, player, "committee")
    assert logged_in(player).post(f"{MEMBERSHIPS}{mine.id}/leave/").status_code == 204
    assert logged_in(player).get(MEMBERSHIPS).json()["results"] == []
    assert not Membership.objects.get(pk=mine.pk).roles.exists()


@pytest.mark.django_db(transaction=True)
def test_two_admins_removing_each_other_concurrently_leave_one_admin():
    """EVAL-005: concurrently remove the two remaining admins; at least one admin remains."""
    first, second = make_user("first@example.com"), make_user("second@example.com")
    club = create_club(first)
    add_member(club, second, "admin")
    clients = {first: logged_in(first), second: logged_in(second)}
    memberships = {user: Membership.objects.get(user=user) for user in (first, second)}
    barrier = threading.Barrier(2)
    statuses = []

    def demote(actor, target):
        try:
            barrier.wait()
            response = clients[actor].put(
                member_roles_url(club, memberships[target]), {"roles": []}, format="json"
            )
            statuses.append(response.status_code)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=demote, args=(first, second)),
        threading.Thread(target=demote, args=(second, first)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert Membership.objects.admins(club).count() == 1
    # The second request runs after the first commits: its actor is no longer an admin (403), or it would
    # remove the last admin (409). Either way it changes nothing.
    assert sorted(statuses)[0] == 200 and sorted(statuses)[1] in (403, 409)
