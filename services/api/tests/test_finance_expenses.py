"""Expenses, receipts and spending transparency (REQ-024, EVAL-024; TASK-040)."""

import uuid

import pytest

from finance.models import Charge
from organizations.models import Role

from .helpers import image_upload, logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


def base(club, tail=""):
    return f"{ORGS}{club.id}/finance/{tail}"


def member(club, name, role=None):
    user = make_user(f"{name.lower()}@example.com", display_name=name)
    add_member(club, user, role) if role else add_member(club, user)
    return user


@pytest.fixture
def kit(staff, club):
    """A one-time campaign of 50000 each for three members; all three pay in full (150000 received)."""
    payers = [member(club, n) for n in ("Ama", "Bo", "Cy")]
    made = staff.post(
        base(club, "campaigns/"),
        {
            "title": "Kit fund",
            "amount_minor": 50000,
            "cadence": "once",
            "starts_on": "2026-10-01",
            "audience": "selected",
            "member_ids": [str(p.id) for p in payers],
        },
        format="json",
    ).json()
    for payer in payers:
        due = Charge.objects.get(member=payer, campaign_id=made["id"])
        payment = staff.post(
            base(club, "payments/"),
            {
                "payer_id": str(payer.id),
                "amount_minor": 50000,
                "method": "mpesa",
                "received_on": "2026-10-02",
                "request_key": str(uuid.uuid4()),
            },
            format="json",
        ).json()
        staff.post(
            base(club, f"payments/{payment['id']}/allocate/"),
            {"charge_id": str(due.id), "amount_minor": 50000},
            format="json",
        )
    return made, payers


def spend(staff, club, campaign, amount, description="Balls", expect=201):
    response = staff.post(
        base(club, "expenses/"),
        {
            "campaign_id": campaign["id"],
            "description": description,
            "amount_minor": amount,
            "spent_on": "2026-10-05",
        },
        format="json",
    )
    assert response.status_code == expect, response.json()
    return response.json()


def kit_row(client, club, path="finance/summary/"):
    rows = client.get(f"{ORGS}{club.id}/{path}").json()
    rows = rows["purposes"] if isinstance(rows, dict) else rows
    return next(r for r in rows if r["title"] == "Kit fund")


def totals(row):
    return row["received_minor"], row["spent_minor"], row["remaining_minor"]


def test_received_spent_and_remaining_reconcile_through_a_reversal_and_a_deficit(staff, club, kit):
    campaign, _ = kit
    assert totals(kit_row(staff, club)) == (150000, 0, 150000)
    spend(staff, club, campaign, 30000, "Nets")
    second = spend(staff, club, campaign, 20000, "Balls")
    assert totals(kit_row(staff, club)) == (150000, 50000, 100000)
    reversed_ = staff.post(
        base(club, f"expenses/{second['id']}/reverse/"), {"reason": "Entered twice"}, format="json"
    ).json()
    assert reversed_["reversed"] is True and reversed_["reversal_reason"] == "Entered twice"
    assert totals(kit_row(staff, club)) == (150000, 30000, 120000)
    spend(staff, club, campaign, 200000, "Table repair")  # more than remains
    assert totals(kit_row(staff, club)) == (150000, 230000, -80000)  # a visible deficit
    assert len(staff.get(base(club, "expenses/")).json()) == 3  # the reversed one is kept


def test_expected_dues_are_not_counted_as_received(staff, club):
    member(club, "Ama")
    staff.post(
        base(club, "campaigns/"),
        {"title": "Kit fund", "amount_minor": 50000, "cadence": "once", "starts_on": "2026-10-01"},
        format="json",
    )
    row = kit_row(staff, club)
    assert (row["received_minor"], row["remaining_minor"]) == (0, 0)
    assert row["expected_minor"] == 100000  # Ama and the admin still owe


def test_members_see_purposes_and_their_own_not_others_or_receipts(staff, club, kit):
    campaign, (ama, bo, _) = kit
    expense = spend(staff, club, campaign, 30000, "Nets")
    with_receipt = staff.put(
        base(club, f"expenses/{expense['id']}/receipt/"),
        {"file": image_upload(name="slip.jpg")},
        format="multipart",
    )
    assert with_receipt.status_code == 200, with_receipt.json()
    receipt = with_receipt.json()["receipt"]
    assert receipt["url"].startswith(f"/api/v1/attachments/{receipt['id']}/content/")
    me = logged_in(ama)
    seen = me.get(f"{ORGS}{club.id}/finance-purposes/").json()
    assert totals(kit_row(me, club, "finance-purposes/")) == (150000, 30000, 120000)
    assert seen["spending"] == [
        {
            "campaign_id": campaign["id"],
            "description": "Nets",
            "amount_minor": 30000,
            "currency": "KES",
            "spent_on": "2026-10-05",
        }
    ]
    body = me.get(f"{ORGS}{club.id}/finance-purposes/").content.decode()
    assert "Bo" not in body and receipt["id"] not in body
    assert me.get(f"/api/v1/attachments/{receipt['id']}/url/").status_code == 404
    assert me.get(base(club, "expenses/")).status_code == 403
    assert me.get(base(club, "summary/")).status_code == 403
    mine = me.get(f"{ORGS}{club.id}/my-finances/").json()
    assert {c["member_id"] for c in mine["charges"]} == {str(ama.id)}
    # Finance viewers read receipts; they can't record.
    auditor = member(
        club, "Auditor", Role.objects.create(organization=club, name="Audit", permissions=["finances.view"])
    )
    audit = logged_in(auditor)
    assert audit.get(f"/api/v1/attachments/{receipt['id']}/url/").status_code == 200
    assert spend(audit, club, campaign, 100, expect=403)
    assert logged_in(make_user("x@example.com")).get(f"{ORGS}{club.id}/finance-purposes/").status_code in (
        403,
        404,
    )


def test_an_expense_must_name_one_of_the_clubs_campaigns_in_its_currency(staff, club, kit):
    campaign, _ = kit
    bad = staff.post(
        base(club, "expenses/"),
        {"campaign_id": str(uuid.uuid4()), "description": "x", "amount_minor": 1, "spent_on": "2026-10-05"},
        format="json",
    )
    assert bad.json()["code"] == "bad_campaign"
    dollars = staff.post(
        base(club, "expenses/"),
        {
            "campaign_id": campaign["id"],
            "description": "x",
            "amount_minor": 1,
            "currency": "USD",
            "spent_on": "2026-10-05",
        },
        format="json",
    )
    assert dollars.json()["code"] == "currency_mismatch"
    general = staff.post(
        base(club, "expenses/"),
        {"description": "Electricity", "amount_minor": 4000, "spent_on": "2026-10-05"},
        format="json",
    )
    assert general.status_code == 201
    rows = staff.get(base(club, "summary/")).json()
    assert next(r for r in rows if r["campaign_id"] is None)["spent_minor"] == 4000
