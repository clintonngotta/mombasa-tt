"""One admin per organization, handed over by nomination (REQ-045, EVAL-045, TASK-105)."""

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
