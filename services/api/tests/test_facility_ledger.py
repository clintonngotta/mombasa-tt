"""Door visits and passes in the ledger, and facility spending (REQ-044, REQ-022, REQ-024; TASK-104)."""

import pytest
from django.core.management import call_command

from finance.models import Allocation, Charge, Payment

from .test_facility_visits import backdate, branch_url, faith, hall, prices, visit  # noqa: F401
from .test_roles import ORGS

pytestmark = pytest.mark.django_db


def base(club, tail=""):
    return f"{ORGS}{club.id}/finance/{tail}"


def general(staff, club):
    return next(r for r in staff.get(base(club, "summary/")).json() if r["campaign_id"] is None)


def test_each_paid_visit_posts_its_charge_payment_and_match_once(staff, club, hall, prices, faith):  # noqa: F811
    walk_in = visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma", method="cash")
    month = visit(
        staff,
        club,
        hall,
        pass_id=prices["month"]["id"],
        player_id=str(faith.id),
        method="mpesa",
        reference="QB2",
    )
    charges = {c["purpose"]: c for c in staff.get(base(club, "charges/")).json()}
    day = charges["Day pass at Tononoka Hall"]
    assert (day["member_id"], day["member_name"], day["kind"], day["status"]) == (
        None,
        "Juma (walk-in)",
        "visit",
        "paid",
    )
    assert charges["Month pass at Tononoka Hall"]["member_name"] == "Faith"
    payments = staff.get(base(club, "payments/")).json()
    assert sorted((p["amount_minor"], p["method"], p["reference"], p["credit_minor"]) for p in payments) == [
        (20000, "cash", "", 0),
        (200000, "mpesa", "QB2", 0),
    ]
    # Back the next day on the month pass: nothing collected, nothing posted.
    backdate(month["id"], 1)
    on_pass = visit(staff, club, hall, player_id=str(faith.id), method="pass")
    assert on_pass["amount_minor"] == 0
    # Posting again (the backfill) changes nothing.
    call_command("post_door_visits")
    assert (Charge.objects.count(), Payment.objects.count(), Allocation.objects.count()) == (2, 2, 2)
    assert walk_in["id"] in {str(c.source_id) for c in Charge.objects.all()}
    # Walk-ins settle at the door: no balance row; Faith owes nothing and has no credit.
    balances = staff.get(base(club, "balances/")).json()
    assert [(b["member_name"], b["owed_minor"], b["credit_minor"]) for b in balances] == [("Faith", 0, 0)]


def test_takings_and_the_ledger_reconcile_through_a_reversal_and_spending(staff, club, hall, prices, faith):  # noqa: F811
    visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma", method="cash")
    mistake = visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma", method="cash")
    visit(
        staff,
        club,
        hall,
        pass_id=prices["month"]["id"],
        player_id=str(faith.id),
        method="mpesa",
        reference="QB2",
    )
    staff.post(branch_url(club, hall, f"visits/{mistake['id']}/reverse/"), {"reason": "Twice"}, format="json")
    takings = staff.get(f"{ORGS}{club.id}/facility-takings/").json()["total"][0]["amount_minor"]
    assert takings == 220000
    assert general(staff, club)["received_minor"] == takings
    reversed_charge = Charge.objects.get(source_id=mistake["id"])
    assert reversed_charge.waived_at is not None and reversed_charge.waive_reason == "Visit reversed: Twice"
    assert Payment.objects.get(request_key=mistake["id"]).reversal_reason == "Visit reversed: Twice"
    # Facility spending comes off the same general purpose, deficits included.
    staff.post(
        base(club, "expenses/"),
        {"description": "Table repair", "amount_minor": 250000, "spent_on": "2026-11-01"},
        format="json",
    )
    row = general(staff, club)
    assert (row["received_minor"], row["spent_minor"], row["remaining_minor"]) == (220000, 250000, -30000)
    # The backfill sees the reversal too and changes nothing more.
    call_command("post_door_visits")
    assert general(staff, club)["received_minor"] == 220000


def test_visits_from_before_the_ledger_are_backfilled_once(staff, club, hall, prices, faith):  # noqa: F811
    kept = visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Juma", method="cash")
    gone = visit(staff, club, hall, pass_id=prices["day"]["id"], walk_in_name="Neema", method="cash")
    staff.post(branch_url(club, hall, f"visits/{gone['id']}/reverse/"), {"reason": "Mistake"}, format="json")
    # As if recorded before TASK-104: nothing in the ledger.
    Allocation.objects.all().delete()
    Payment.objects.all().delete()
    Charge.objects.all().delete()
    call_command("post_door_visits")
    call_command("post_door_visits")
    assert Charge.objects.count() == 2 and Payment.objects.count() == 2
    assert Charge.objects.get(source_id=gone["id"]).waived_at is not None
    assert Charge.objects.get(source_id=kept["id"]).waived_at is None
    assert general(staff, club)["received_minor"] == 20000
