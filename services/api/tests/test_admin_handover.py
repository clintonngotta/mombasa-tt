"""Up to three admins per organization, changed by nomination (REQ-045, EVAL-045, TASK-105, TASK-139)."""

import threading

import pytest
from django.core import mail
from django.db import connection

from organizations.models import AdminHandover, Membership

from .helpers import logged_in, make_user
from .test_ratings import work
from .test_roles import ORGS, add_member, create_club

pytestmark = pytest.mark.django_db
NOMINATIONS = "/api/v1/me/admin-nominations/"


def admin_url(club, action=""):
    return f"{ORGS}{club.id}/admin/" + (f"{action}/" if action else "")


@pytest.fixture
def founder(db):
    return make_user("founder@example.com", display_name="Founder")


@pytest.fixture
def club(founder):
    return create_club(founder)


def the_admin(club):
    return Membership.objects.admins(club).get().user


def test_the_admin_nominates_a_successor_who_accepts(founder, club):
    successor = make_user("next@example.com", display_name="Next Up")
    their = add_member(club, successor, "captain")
    bystander = make_user("member@example.com")
    add_member(club, bystander)
    client = logged_in(founder)

    # Nobody but the admin nominates; only active members can be nominated.
    assert (
        logged_in(successor)
        .post(admin_url(club, "nominate"), {"membership_id": str(their.id)}, format="json")
        .status_code
        == 403
    )
    outsider = add_member(create_club(make_user("other@example.com"), "Other"), make_user("o@example.com"))
    assert (
        client.post(
            admin_url(club, "nominate"), {"membership_id": str(outsider.id)}, format="json"
        ).status_code
        == 400
    )

    mail.outbox.clear()
    nominated = client.post(admin_url(club, "nominate"), {"membership_id": str(their.id)}, format="json")
    assert nominated.status_code == 201 and nominated.json()["status"] == "pending"
    work()
    assert [m.to for m in mail.outbox] == [[successor.email]]

    # Members see who the admin is; the open nomination only those it concerns, history only role managers.
    seen = logged_in(bystander).get(admin_url(club)).json()
    assert seen["admin"]["display_name"] == "Founder" and seen["pending"] is None and seen["history"] is None
    assert [a["display_name"] for a in seen["admins"]] == ["Founder"] and seen["nominations"] == []
    assert seen["limit"] == 3
    assert logged_in(make_user("x@example.com")).get(admin_url(club)).status_code == 403

    mine = logged_in(successor).get(NOMINATIONS).json()["results"]
    assert [n["organization"]["name"] for n in mine] == ["Coast TT Club"]
    assert logged_in(bystander).post(f"{NOMINATIONS}{mine[0]['id']}/accept/").status_code == 404
    accepted = logged_in(successor).post(f"{NOMINATIONS}{mine[0]['id']}/accept/")
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"

    assert the_admin(club) == successor
    # The previous admin is an ordinary member now; the new one keeps the roles they had.
    assert not Membership.objects.get(user=founder).roles.exists()
    assert {r.key for r in Membership.objects.get(user=successor).roles.all()} == {"admin", "captain"}
    history = logged_in(successor).get(admin_url(club)).json()["history"]
    assert [(h["from_user"]["display_name"], h["to_user"]["display_name"]) for h in history] == [
        ("Founder", "Next Up")
    ]
    # The former admin can leave now.
    assert (
        client.post(f"/api/v1/me/memberships/{Membership.objects.get(user=founder).id}/leave/").status_code
        == 204
    )


def test_nominations_can_be_declined_cancelled_and_replaced(founder, club):
    first, second = make_user("a@example.com"), make_user("b@example.com")
    a, b = add_member(club, first), add_member(club, second)
    client = logged_in(founder)
    one = client.post(admin_url(club, "nominate"), {"membership_id": str(a.id)}, format="json").json()
    two = client.post(admin_url(club, "nominate"), {"membership_id": str(b.id)}, format="json").json()
    assert AdminHandover.objects.get(pk=one["id"]).status == "cancelled"
    # The replaced nomination can't be accepted.
    assert logged_in(first).post(f"{NOMINATIONS}{one['id']}/accept/").status_code == 409
    assert logged_in(second).post(f"{NOMINATIONS}{two['id']}/decline/").json()["status"] == "declined"
    assert client.post(admin_url(club, "cancel")).status_code == 409

    three = client.post(admin_url(club, "nominate"), {"membership_id": str(a.id)}, format="json").json()
    assert client.post(admin_url(club, "cancel")).json()["status"] == "cancelled"
    assert logged_in(first).post(f"{NOMINATIONS}{three['id']}/accept/").status_code == 409
    assert the_admin(club) == founder
    # Nominating yourself is refused.
    me = Membership.objects.get(user=founder)
    assert (
        client.post(admin_url(club, "nominate"), {"membership_id": str(me.id)}, format="json").status_code
        == 400
    )


def test_a_nomination_lapses_if_the_nominee_leaves(founder, club):
    nominee = make_user("n@example.com")
    membership = add_member(club, nominee)
    handover = (
        logged_in(founder)
        .post(admin_url(club, "nominate"), {"membership_id": str(membership.id)}, format="json")
        .json()
    )
    assert logged_in(nominee).post(f"/api/v1/me/memberships/{membership.id}/leave/").status_code == 204
    lapsed = logged_in(nominee).post(f"{NOMINATIONS}{handover['id']}/accept/")
    assert lapsed.status_code == 409 and lapsed.json()["code"] == "nomination_lapsed"
    assert the_admin(club) == founder


def test_a_platform_super_admin_appoints_an_admin_when_the_admin_is_gone(founder, club):
    founder.is_active = False
    founder.save(update_fields=["is_active"])
    helper = make_user("helper@example.com")
    membership = add_member(club, helper, "committee")
    body = {"membership_id": str(membership.id), "reason": "The admin's account is closed"}
    assert logged_in(helper).post(admin_url(club, "appoint"), body, format="json").status_code == 403
    root = logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))
    assert (
        root.post(
            admin_url(club, "appoint"), {"membership_id": str(membership.id)}, format="json"
        ).status_code
        == 400
    )
    appointed = root.post(admin_url(club, "appoint"), body, format="json")
    assert appointed.status_code == 201
    assert (appointed.json()["kind"], appointed.json()["reason"]) == ("appointment", body["reason"])
    holders = Membership.objects.filter(organization=club, roles__key="admin")
    assert [m.user for m in holders] == [helper]


def nominate_as(client, club, membership, kind="addition"):
    return client.post(
        admin_url(club, "nominate"), {"membership_id": str(membership.id), "kind": kind}, format="json"
    )


def admin_names(club):
    return sorted(m.user.display_name for m in Membership.objects.admins(club))


def test_an_admin_adds_further_admins_up_to_three(founder, club):
    people = [make_user(f"p{n}@example.com", display_name=f"P{n}") for n in range(4)]
    theirs = [add_member(club, person) for person in people]
    client = logged_in(founder)
    mail.outbox.clear()

    first = nominate_as(client, club, theirs[0])
    assert first.status_code == 201 and first.json()["kind"] == "addition"
    work()
    assert "further admin" in mail.outbox[0].body
    # Nothing changes until the nominee accepts; the founder stays an admin beside them.
    assert admin_names(club) == ["Founder"]
    assert logged_in(people[0]).post(f"{NOMINATIONS}{first.json()['id']}/accept/").status_code == 200
    assert admin_names(club) == ["Founder", "P0"]
    assert {r.key for r in Membership.objects.get(user=founder).roles.all()} == {"admin"}

    # The new admin has the same authority: they offer the third place. Open offers count.
    second = nominate_as(logged_in(people[0]), club, theirs[1])
    assert second.status_code == 201
    over = nominate_as(client, club, theirs[2])
    assert over.status_code == 409 and over.json()["code"] == "admin_limit"
    # An admin sees every open nomination; so does the nominee, of their own.
    seen = client.get(admin_url(club)).json()
    assert [n["to_user"]["display_name"] for n in seen["nominations"]] == ["P1"]
    assert [a["display_name"] for a in seen["admins"]] == ["Founder", "P0"]
    # Any admin withdraws an offer of a further place, which frees it.
    withdrawn = client.post(admin_url(club, "cancel"), {"handover_id": second.json()["id"]}, format="json")
    assert withdrawn.json()["status"] == "cancelled"
    third = nominate_as(client, club, theirs[2])
    assert logged_in(people[2]).post(f"{NOMINATIONS}{third.json()['id']}/accept/").status_code == 200
    assert admin_names(club) == ["Founder", "P0", "P2"]

    # Three is the limit, in the nomination and in the role editor.
    full = nominate_as(client, club, theirs[3])
    assert full.status_code == 409 and full.json()["code"] == "admin_limit"
    admin_role = club.roles.get(key="admin")
    edited = client.put(
        f"{ORGS}{club.id}/members/{theirs[3].id}/roles/", {"roles": [str(admin_role.id)]}, format="json"
    )
    assert edited.status_code == 409 and edited.json()["code"] == "admin_by_handover"
    assert nominate_as(client, club, theirs[0]).json()["code"] == "already_admin"
    # A full organization still hands a place over: the successor takes the nominator's.
    handed = nominate_as(logged_in(people[2]), club, theirs[3], kind="nomination")
    assert logged_in(people[3]).post(f"{NOMINATIONS}{handed.json()['id']}/accept/").status_code == 200
    assert admin_names(club) == ["Founder", "P0", "P3"]
    assert Membership.objects.filter(organization=club, roles__key="admin").count() == 3


def test_an_offer_accepted_after_the_places_filled_is_refused(founder, club):
    a, b, c = (make_user(f"{n}@example.com", display_name=n.upper()) for n in "abc")
    ma, mb, mc = (add_member(club, person) for person in (a, b, c))
    client = logged_in(founder)
    one = nominate_as(client, club, ma).json()
    two = nominate_as(client, club, mb).json()
    # A platform appointment takes the last place while both offers are open.
    root = logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))
    body = {"membership_id": str(mc.id), "reason": "Asked for by the committee"}
    assert root.post(admin_url(club, "appoint"), body, format="json").status_code == 201
    assert logged_in(a).post(f"{NOMINATIONS}{one['id']}/accept/").status_code == 200
    late = logged_in(b).post(f"{NOMINATIONS}{two['id']}/accept/")
    assert late.status_code == 409 and late.json()["code"] == "admin_limit"
    assert admin_names(club) == ["A", "C", "Founder"]
    # With every place taken by a working account, the platform must say whom the appointee replaces.
    body = {"membership_id": str(mb.id), "reason": "Dispute settled by the region"}
    assert root.post(admin_url(club, "appoint"), body, format="json").json()["code"] == "admin_limit"
    wrong = root.post(admin_url(club, "appoint"), body | {"replace_membership_id": str(mb.id)}, format="json")
    assert wrong.status_code == 400 and wrong.json()["code"] == "not_an_admin"
    swapped = root.post(
        admin_url(club, "appoint"), body | {"replace_membership_id": str(ma.id)}, format="json"
    )
    assert swapped.status_code == 201 and swapped.json()["from_user"]["display_name"] == "A"
    assert admin_names(club) == ["B", "C", "Founder"]


def test_an_admin_steps_down_only_while_another_remains(founder, club):
    other = make_user("other@example.com", display_name="Other")
    membership = add_member(club, other, "captain")
    bystander = make_user("member@example.com")
    waiting = add_member(club, bystander)
    client = logged_in(founder)
    alone = client.post(admin_url(club, "step-down"))
    assert alone.status_code == 409 and alone.json()["code"] == "last_admin"
    assert logged_in(other).post(admin_url(club, "step-down")).status_code == 403

    offer = nominate_as(client, club, membership).json()
    logged_in(other).post(f"{NOMINATIONS}{offer['id']}/accept/")
    # Admins are equals: neither removes the other from the club.
    kicked = client.post(f"{ORGS}{club.id}/members/{membership.id}/remove/")
    assert kicked.status_code == 409 and kicked.json()["code"] == "admin_by_handover"
    # The founder's open offer lapses with their authority.
    open_offer = nominate_as(client, club, waiting).json()
    left = client.post(admin_url(club, "step-down"))
    assert left.status_code == 200 and left.json()["kind"] == "step_down"
    assert admin_names(club) == ["Other"]
    assert not Membership.objects.get(user=founder).roles.exists()
    assert AdminHandover.objects.get(pk=open_offer["id"]).status == "cancelled"
    assert logged_in(bystander).post(f"{NOMINATIONS}{open_offer['id']}/accept/").status_code == 409
    # The former admin is an ordinary member: no nominating, and the history shows the step-down.
    assert nominate_as(client, club, waiting).status_code == 403
    history = logged_in(other).get(admin_url(club)).json()["history"]
    assert [h["kind"] for h in history][0] == "step_down"
    # The one admin left can't go.
    assert logged_in(other).post(admin_url(club, "step-down")).json()["code"] == "last_admin"


def test_only_the_nominator_cancels_a_successor(founder, club):
    second, heir = make_user("second@example.com"), make_user("heir@example.com")
    ms, mh = add_member(club, second), add_member(club, heir)
    client = logged_in(founder)
    offer = nominate_as(client, club, ms).json()
    logged_in(second).post(f"{NOMINATIONS}{offer['id']}/accept/")
    handover = nominate_as(client, club, mh, kind="nomination").json()
    body = {"handover_id": handover["id"]}
    assert logged_in(second).post(admin_url(club, "cancel"), body, format="json").status_code == 403
    assert logged_in(heir).post(admin_url(club, "cancel"), body, format="json").status_code == 403
    assert client.post(admin_url(club, "cancel"), body, format="json").json()["status"] == "cancelled"


@pytest.mark.django_db(transaction=True)
def test_two_offers_accepted_at_once_never_pass_three_admins():
    founder = make_user("f@example.com")
    club = create_club(founder)
    people = [make_user(f"n{n}@example.com") for n in range(3)]
    theirs = [add_member(club, person) for person in people]
    client = logged_in(founder)
    first = nominate_as(client, club, theirs[0]).json()
    assert logged_in(people[0]).post(f"{NOMINATIONS}{first['id']}/accept/").status_code == 200
    # Two offers for the one place left can't both be made through the API, so the second is made directly.
    offers = [
        AdminHandover.objects.create(
            organization=club, kind="addition", from_user=founder, to_user=person, created_by=founder
        )
        for person in people[1:]
    ]
    barrier = threading.Barrier(2)
    statuses = []

    def run(person, offer):
        try:
            barrier.wait()
            statuses.append(logged_in(person).post(f"{NOMINATIONS}{offer.id}/accept/").status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=pair) for pair in zip(people[1:], offers, strict=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [200, 409]
    assert Membership.objects.filter(organization=club, roles__key="admin").count() == 3


@pytest.mark.django_db(transaction=True)
def test_accepting_and_cancelling_at_once_leave_exactly_one_admin():
    founder, nominee = make_user("f@example.com"), make_user("n@example.com")
    club = create_club(founder)
    membership = add_member(club, nominee)
    clients = {"founder": logged_in(founder), "nominee": logged_in(nominee)}
    handover = (
        clients["founder"]
        .post(admin_url(club, "nominate"), {"membership_id": str(membership.id)}, format="json")
        .json()
    )
    barrier = threading.Barrier(2)
    statuses = {}

    def run(who, path):
        try:
            barrier.wait()
            statuses[who] = clients[who].post(path).status_code
        finally:
            connection.close()

    threads = [
        threading.Thread(target=run, args=("founder", admin_url(club, "cancel"))),
        threading.Thread(target=run, args=("nominee", f"{NOMINATIONS}{handover['id']}/accept/")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert Membership.objects.filter(organization=club, roles__key="admin").count() == 1
    assert sorted(statuses.values()) in ([200, 403], [200, 409])
