"""Charges, payments, allocations, credit and reversals (REQ-022, EVAL-022; TASK-037)."""

import uuid

import pytest

from finance.models import Allocation, Payment
from organizations.models import Role

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


def base(club, tail=""):
    return f"{ORGS}{club.id}/finance/{tail}"


@pytest.fixture
def ama(club):
    user = make_user("ama@example.com", display_name="Ama")
    add_member(club, user)
    return user


def charge(staff, club, member, amount=100000, **body):
    payload = {
        "member_id": str(member.id),
        "purpose": "Event fee",
        "kind": "event_fee",
        "amount_minor": amount,
        **body,
    }
    response = staff.post(base(club, "charges/"), payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def pay(staff, club, member, amount, key=None, expect=201, **body):
    payload = {
        "payer_id": str(member.id),
        "amount_minor": amount,
        "method": "mpesa",
        "reference": "QX1",
        "received_on": "2026-11-19",
        "request_key": str(key or uuid.uuid4()),
        **body,
    }
    response = staff.post(base(club, "payments/"), payload, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def allocate(staff, club, payment, the_charge, amount, expect=200):
    response = staff.post(
        base(club, f"payments/{payment['id']}/allocate/"),
        {"charge_id": the_charge["id"], "amount_minor": amount},
        format="json",
    )
    assert response.status_code == expect, response.json()
    return response.json()


def outstanding(staff, club, the_charge):
    found = {c["id"]: c for c in staff.get(base(club, "charges/")).json()}
    return found[the_charge["id"]]["outstanding_minor"]


def test_the_balance_runs_100000_60000_0_then_60000_after_a_reversal(staff, club, ama):
    fee = charge(staff, club, ama)
    assert outstanding(staff, club, fee) == 100000
    first = pay(staff, club, ama, 40000)
    allocate(staff, club, first, fee, 40000)
    assert outstanding(staff, club, fee) == 60000
    key = uuid.uuid4()
    second = pay(staff, club, ama, 60000, key=key)
    allocate(staff, club, second, fee, 60000)
    assert outstanding(staff, club, fee) == 0
    # The same request again records nothing new.
    again = pay(staff, club, ama, 60000, key=key, expect=200)
    assert again["id"] == second["id"] and Payment.objects.count() == 2
    reversed_ = staff.post(
        base(club, f"payments/{second['id']}/reverse/"), {"reason": "Wrong member"}, format="json"
    )
    assert reversed_.json()["reversed"] is True and reversed_.json()["reversal_reason"] == "Wrong member"
    assert outstanding(staff, club, fee) == 60000
    # Original and reversal are both kept.
    assert Payment.objects.count() == 2 and Allocation.objects.count() == 2
    assert (
        staff.post(
            base(club, f"payments/{second['id']}/reverse/"), {"reason": "x"}, format="json"
        ).status_code
        == 409
    )


def test_excess_stays_visible_credit_and_over_allocation_and_currency_mismatch_fail(staff, club, ama):
    fee = charge(staff, club, ama, amount=50000)
    payment = pay(staff, club, ama, 80000)
    assert allocate(staff, club, payment, fee, 60000, expect=400)["code"] == "over_allocated"
    shown = allocate(staff, club, payment, fee, 50000)
    assert (shown["allocated_minor"], shown["credit_minor"]) == (50000, 30000)
    other = charge(staff, club, ama, amount=10000)
    assert allocate(staff, club, payment, other, 40000, expect=400)["code"] == "over_allocated"
    dollars = charge(staff, club, ama, amount=1000, currency="USD")
    assert allocate(staff, club, payment, dollars, 1000, expect=400)["code"] == "currency_mismatch"
    balances = staff.get(base(club, "balances/")).json()
    ama_kes = next(b for b in balances if b["member_name"] == "Ama" and b["currency"] == "KES")
    assert (ama_kes["owed_minor"], ama_kes["credit_minor"]) == (10000, 30000)


def test_a_waived_charge_owes_nothing_and_takes_no_payment(staff, club, ama):
    fee = charge(staff, club, ama, amount=20000)
    waived = staff.post(base(club, f"charges/{fee['id']}/waive/"), {"reason": "Junior"}, format="json").json()
    assert (waived["status"], waived["outstanding_minor"], waived["waive_reason"]) == ("waived", 0, "Junior")
    payment = pay(staff, club, ama, 20000)
    assert allocate(staff, club, payment, fee, 20000, expect=409)["code"] == "charge_waived"


def test_statuses_pending_partial_paid_and_overdue(staff, club, ama):
    late = charge(staff, club, ama, amount=10000, due_on="2026-01-01")
    soon = charge(staff, club, ama, amount=10000, due_on="2099-01-01")
    payment = pay(staff, club, ama, 15000)
    allocate(staff, club, payment, late, 5000)
    allocate(staff, club, payment, soon, 10000)
    statuses = {c["id"]: c["status"] for c in staff.get(base(club, "charges/")).json()}
    assert (statuses[late["id"]], statuses[soon["id"]]) == (
        "overdue",
        "paid",
    )  # partly paid and late is overdue
    fresh = charge(staff, club, ama, amount=10000, due_on="2099-01-01")
    allocate(staff, club, pay(staff, club, ama, 4000), fresh, 4000)
    assert {c["id"]: c["status"] for c in staff.get(base(club, "charges/")).json()}[fresh["id"]] == "partial"


def test_members_see_only_their_own_and_only_finance_staff_record(staff, club, ama):
    bo = make_user("bo@example.com", display_name="Bo")
    add_member(club, bo)
    charge(staff, club, ama, purpose="MARK-AMA-FEE")
    charge(staff, club, bo, purpose="Bo's fee")
    mine = logged_in(ama).get(f"{ORGS}{club.id}/my-finances/").json()
    assert [c["purpose"] for c in mine["charges"]] == ["MARK-AMA-FEE"]
    assert "MARK-AMA-FEE" not in logged_in(bo).get(f"{ORGS}{club.id}/my-finances/").content.decode()
    member = logged_in(ama)
    assert member.get(base(club, "charges/")).status_code == 403
    assert member.post(base(club, "charges/"), {}, format="json").status_code == 403
    viewer_role = Role.objects.create(organization=club, name="Auditor", permissions=["finances.view"])
    auditor = make_user("auditor@example.com")
    add_member(club, auditor, viewer_role)
    audit = logged_in(auditor)
    assert audit.get(base(club, "charges/")).status_code == 200
    assert audit.post(base(club, "charges/"), {}, format="json").status_code == 403
    outsider = make_user("outsider@example.com")
    payload = {"member_id": str(outsider.id), "purpose": "x", "amount_minor": 1}
    assert staff.post(base(club, "charges/"), payload, format="json").json()["code"] == "not_a_member"
