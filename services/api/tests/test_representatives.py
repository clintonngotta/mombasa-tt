"""Representatives (REQ-045, EVAL-045, TASK-108): clubs nominate members to their region's body and a
regional body to the national one; the receiving body accepts or declines within its cap; the sender
recalls or replaces; leaving ends it; the body sees a name and an organization only."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from notifications.models import Notification
from organizations.models import Membership, Organization, Representative, seed_roles
from organizations.permissions import RoleKey

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member, create_club

pytestmark = pytest.mark.django_db


def url(organization, path=""):
    return f"{ORGS}{organization.id}/representatives/{path}"


def make_body(name, admin, *, kind="regional_body", region="Mombasa"):
    body = Organization.objects.create(name=name, town="Mombasa", country="KE", region=region, kind=kind)
    add_member(body, admin, seed_roles(body)[RoleKey.ADMIN])
    return body


@pytest.fixture
def coast(club):
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    return club


@pytest.fixture
def chair():
    return make_user("chair@example.com", display_name="Body Chair")


@pytest.fixture
def body(chair):
    return make_body("Mombasa Region TT", chair)


@pytest.fixture
def desk(chair):
    return logged_in(chair)


def member_of(club, email, name, **extra):
    user = make_user(email, display_name=name, **extra)
    return user, add_member(club, user)


def nominate(client, sender, membership, **extra):
    return client.post(url(sender), {"membership_id": str(membership.id), **extra}, format="json")


def test_a_club_nominates_and_the_body_accepts_one_and_declines_another(coast, staff, body, desk, chair):
    rita, rita_m = member_of(coast, "rita@example.com", "Rita Rep")
    sam, sam_m = member_of(coast, "sam@example.com", "Sam Second")

    first = nominate(staff, coast, rita_m, term_start="2026-01-01", term_end="2027-12-31")
    assert first.status_code == 201, first.json()
    assert first.json()["status"] == "pending" and first.json()["body"]["name"] == "Mombasa Region TT"
    second = nominate(staff, coast, sam_m)
    assert second.status_code == 201
    # The nominee and the body's admin are told.
    told = set(Notification.objects.filter(category="governance").values_list("recipient_id", flat=True))
    assert {rita.id, chair.id} <= told

    received = desk.get(url(body)).json()
    assert received["receives"] and received["can_manage"]
    assert [r["person"]["display_name"] for r in received["received"]] == ["Rita Rep", "Sam Second"]

    accepted = desk.post(url(body, f"{first.json()['id']}/accept/"))
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    note = {"note": "One is enough"}
    declined = desk.post(url(body, f"{second.json()['id']}/decline/"), note, format="json")
    assert declined.json()["status"] == "declined" and declined.json()["note"] == "One is enough"
    # A decision is made once.
    assert desk.post(url(body, f"{first.json()['id']}/accept/")).status_code == 409
    assert desk.post(url(body, f"{second.json()['id']}/accept/")).status_code == 409

    # A plain member of the club sees who represents it, not the declined nomination.
    seen = logged_in(sam).get(url(coast)).json()
    assert not seen["can_manage"]
    assert [(r["person"]["display_name"], r["status"]) for r in seen["sent"]] == [("Rita Rep", "accepted")]
    assert [r["status"] for r in logged_in(rita).get(url(coast)).json()["sent"]] == ["accepted"]


def test_the_body_sees_a_name_and_a_club_and_nothing_else(coast, staff, body, desk):
    rita, rita_m = member_of(coast, "rita@example.com", "Rita Rep", phone="+254700000001")
    made = nominate(staff, coast, rita_m).json()
    desk.post(url(body, f"{made['id']}/accept/"))
    response = desk.get(url(body))
    row = response.json()["received"][0]
    assert row["person"] == {"id": str(rita.id), "display_name": "Rita Rep"}
    assert row["sender"] == {"id": str(coast.id), "name": coast.name}
    assert set(row) == {
        "id",
        "person",
        "sender",
        "body",
        "status",
        "end_reason",
        "term_start",
        "term_end",
        "in_term",
        "replaces",
        "note",
        "created_at",
        "decided_at",
        "ended_at",
    }
    assert "rita@example.com" not in response.content.decode()
    assert "+254700000001" not in response.content.decode()


def test_the_cap_refuses_one_too_many_and_replacing_stays_within_it(coast, staff, body, desk):
    _, a = member_of(coast, "a@example.com", "Ann A")
    _, b = member_of(coast, "b@example.com", "Ben B")
    _, c = member_of(coast, "c@example.com", "Cat C")
    assert desk.put(url(body, "cap/"), {"cap": 2}, format="json").json() == {"cap": 2}
    assert staff.get(url(coast)).json()["cap"] == 2

    first = nominate(staff, coast, a).json()
    assert nominate(staff, coast, b).status_code == 201
    over = nominate(staff, coast, c)
    assert over.status_code == 409 and over.json()["code"] == "over_cap"
    # The same person twice is refused too.
    assert nominate(staff, coast, a).status_code == 409

    # Replacing an accepted representative takes no extra place; the old one ends when the new is accepted.
    desk.post(url(body, f"{first['id']}/accept/"))
    swap = nominate(staff, coast, c, replaces=first["id"])
    assert swap.status_code == 201, swap.json()
    assert Representative.objects.get(pk=first["id"]).status == "accepted"
    assert desk.post(url(body, f"{swap.json()['id']}/accept/")).status_code == 200
    old = Representative.objects.get(pk=first["id"])
    assert (old.status, old.end_reason) == ("ended", "replaced")

    # A lowered cap stops further acceptances.
    desk.put(url(body, "cap/"), {"cap": 1}, format="json")
    pending = Representative.objects.get(sender=coast, status="pending")
    refused = desk.post(url(body, f"{pending.id}/accept/"))
    assert refused.status_code == 409 and refused.json()["code"] == "over_cap"
    # No limit again.
    assert desk.put(url(body, "cap/"), {"cap": None}, format="json").json() == {"cap": None}
    assert desk.post(url(body, f"{pending.id}/accept/")).status_code == 200


def test_another_clubs_places_do_not_count_towards_this_clubs_cap(coast, staff, body, desk):
    other_admin = make_user("other@example.com", display_name="Other Admin")
    nyali = create_club(other_admin, "Nyali TT")
    nyali.country, nyali.region = "KE", "mombasa"  # the region matches whatever its case
    nyali.save(update_fields=["country", "region"])
    desk.put(url(body, "cap/"), {"cap": 1}, format="json")
    _, a = member_of(coast, "a@example.com", "Ann A")
    assert nominate(staff, coast, a).status_code == 201
    theirs = Membership.objects.get(organization=nyali, user=other_admin)
    assert nominate(logged_in(other_admin), nyali, theirs).status_code == 201


def test_leaving_the_club_ends_the_place_and_withdraws_a_nomination(coast, staff, body, desk):
    rita, rita_m = member_of(coast, "rita@example.com", "Rita Rep")
    sam, sam_m = member_of(coast, "sam@example.com", "Sam Second")
    accepted = nominate(staff, coast, rita_m).json()
    desk.post(url(body, f"{accepted['id']}/accept/"))
    waiting = nominate(staff, coast, sam_m).json()

    assert logged_in(rita).post(f"/api/v1/me/memberships/{rita_m.id}/leave/").status_code == 204
    assert staff.post(f"{ORGS}{coast.id}/members/{sam_m.id}/remove/").status_code in {200, 204}

    gone = Representative.objects.get(pk=accepted["id"])
    assert (gone.status, gone.end_reason) == ("ended", "left") and gone.ended_at
    assert Representative.objects.get(pk=waiting["id"]).status == "withdrawn"
    assert [r for r in desk.get(url(body)).json()["received"] if r["status"] in ("pending", "accepted")] == []
    # The body can't accept somebody who has gone.
    assert desk.post(url(body, f"{waiting['id']}/accept/")).status_code == 409


def test_the_club_recalls_and_the_body_removes(coast, staff, body, desk):
    _, a = member_of(coast, "a@example.com", "Ann A")
    _, b = member_of(coast, "b@example.com", "Ben B")
    one = nominate(staff, coast, a).json()
    two = nominate(staff, coast, b).json()
    # A nomination taken back before a decision is withdrawn.
    assert staff.post(url(coast, f"{two['id']}/withdraw/")).json()["status"] == "withdrawn"
    assert staff.post(url(coast, f"{two['id']}/withdraw/")).status_code == 409
    desk.post(url(body, f"{one['id']}/accept/"))
    removed = desk.post(url(body, f"{one['id']}/remove/"), {"note": "Stopped attending"}, format="json")
    assert (removed.json()["status"], removed.json()["end_reason"]) == ("ended", "removed")
    # The same member can be sent again afterwards, and recalled by the club once accepted.
    again = nominate(staff, coast, a).json()
    desk.post(url(body, f"{again['id']}/accept/"))
    recalled = staff.post(url(coast, f"{again['id']}/withdraw/")).json()
    assert (recalled["status"], recalled["end_reason"]) == ("ended", "recalled")


def test_a_term_that_has_run_out_frees_the_place(coast, staff, body, desk):
    _, a = member_of(coast, "a@example.com", "Ann A")
    _, b = member_of(coast, "b@example.com", "Ben B")
    desk.put(url(body, "cap/"), {"cap": 1}, format="json")
    one = nominate(staff, coast, a).json()
    desk.post(url(body, f"{one['id']}/accept/"))
    yesterday = timezone.localdate() - timedelta(days=2)
    Representative.objects.filter(pk=one["id"]).update(term_end=yesterday)
    listed = staff.get(url(coast)).json()["sent"][0]
    assert listed["in_term"] is False
    assert nominate(staff, coast, b).status_code == 201
    lapsed = Representative.objects.get(pk=one["id"])
    assert (lapsed.status, lapsed.end_reason) == ("ended", "term_ended")


def test_a_regional_body_nominates_to_the_national_body(coast, body, desk, chair):
    head = make_user("head@example.com", display_name="National Head")
    national = make_body("Kenya TT", head, kind="national_body", region="")
    delegate, delegate_m = member_of(body, "delegate@example.com", "Dora Delegate")
    made = nominate(desk, body, delegate_m)
    assert made.status_code == 201, made.json()
    assert made.json()["body"]["id"] == str(national.id)
    # The regional body both sends and receives.
    both = desk.get(url(body)).json()
    assert both["receives"] and both["body"]["id"] == str(national.id) and len(both["sent"]) == 1
    assert logged_in(head).post(url(national, f"{made.json()['id']}/accept/")).status_code == 200
    # A club member can't be sent to the national body by the region, and the national body sends nobody.
    _, club_member = member_of(coast, "rita@example.com", "Rita Rep")
    assert nominate(desk, body, club_member).status_code == 400
    theirs = Membership.objects.get(organization=national, user=head)
    assert nominate(logged_in(head), national, theirs).status_code == 409


def test_who_may_do_what(coast, staff, body, desk, admin):
    rita, rita_m = member_of(coast, "rita@example.com", "Rita Rep")
    outsider = logged_in(make_user("outsider@example.com"))
    plain = logged_in(rita)
    made = nominate(staff, coast, rita_m).json()
    rep = f"{made['id']}/"

    # Signed out, outsiders and plain members change nothing.
    assert APIClient().get(url(coast)).status_code == 401
    assert outsider.get(url(coast)).status_code == 403
    assert outsider.get(url(body)).status_code == 403
    assert plain.post(url(coast), {"membership_id": str(rita_m.id)}, format="json").status_code == 403
    assert plain.post(url(coast, rep + "withdraw/")).status_code == 403
    # The club decides nothing on the body's side, and can't set the body's cap or its own.
    for action in ("accept/", "decline/", "remove/"):
        assert staff.post(url(body, rep + action)).status_code == 403
        assert staff.post(url(coast, rep + action)).status_code == 404  # not a nomination to the club
    assert staff.put(url(body, "cap/"), {"cap": 1}, format="json").status_code == 403
    assert staff.put(url(coast, "cap/"), {"cap": 1}, format="json").status_code == 409
    # The body can't withdraw for the club, and another body can't decide.
    assert desk.post(url(body, rep + "withdraw/")).status_code == 404
    kilifi_chair = make_user("kilifi@example.com")
    kilifi = make_body("Kilifi Region TT", kilifi_chair, region="Kilifi")
    assert logged_in(kilifi_chair).post(url(kilifi, rep + "accept/")).status_code == 404
    assert Representative.objects.get(pk=made["id"]).status == "pending"
    # A club official holding only tournament approval in the body decides nothing here.
    official = make_user("official@example.com")
    add_member(body, official, RoleKey.OFFICIAL)
    assert logged_in(official).post(url(body, rep + "accept/")).status_code == 403


def test_input_is_checked(coast, staff, body, desk):
    _, a = member_of(coast, "a@example.com", "Ann A")
    other = create_club(make_user("other@example.com"), "Elsewhere TT")
    stranger = Membership.objects.get(organization=other)
    assert nominate(staff, coast, stranger).status_code == 400
    assert nominate(staff, coast, a, term_start="2027-01-01", term_end="2026-01-01").status_code == 400
    assert nominate(staff, coast, a, role="admin").status_code == 400  # unknown field
    assert nominate(staff, coast, a, replaces="00000000-0000-4000-8000-000000000001").status_code == 400
    for cap in (0, 21, "many"):
        assert desk.put(url(body, "cap/"), {"cap": cap}, format="json").status_code == 400
    assert desk.put(url(body, "cap/"), {"cap": 2, "extra": 1}, format="json").status_code == 400
    made = nominate(staff, coast, a).json()
    long_note = {"note": "x" * 301}
    assert desk.post(url(body, f"{made['id']}/decline/"), long_note, format="json").status_code == 400
    # A club in a region without a body has nowhere to send anyone.
    coast.region = "Lamu"
    coast.save(update_fields=["region"])
    refused = nominate(staff, coast, a)
    assert refused.status_code == 409 and refused.json()["code"] == "no_body"
    assert staff.get(url(coast)).json()["body"] is None


def test_the_list_costs_the_same_however_many_there_are(coast, staff, body, desk):
    def count():
        with CaptureQueriesContext(connection) as queries:
            assert desk.get(url(body)).status_code == 200
        return len(queries)

    _, first = member_of(coast, "first@example.com", "First")
    nominate(staff, coast, first)
    one = count()
    for i in range(4):
        _, m = member_of(coast, f"m{i}@example.com", f"Member {i}")
        nominate(staff, coast, m)
    assert count() == one
