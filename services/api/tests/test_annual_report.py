"""The annual financial report (REQ-041, TASK-079): expense categories, the financial year, figures that
reconcile with the ledger, who reads a report, the frozen snapshot, amendments and exports."""

import csv
import io
import uuid
from datetime import date, timedelta

import pytest
from django.utils import timezone

from finance import reports
from finance.models import Allocation, AnnualReport, Campaign, Charge, Expense, Payment
from organizations.models import Role

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


def url(club, tail=""):
    return f"{ORGS}{club.id}/{tail}"


def last_year() -> tuple[date, date]:
    year = timezone.localdate().year - 1
    return date(year, 1, 1), date(year, 12, 31)


def pay(club, member, amount, on, charge=None, **extra) -> Payment:
    payment = Payment.objects.create(
        organization=club,
        payer=member,
        amount_minor=amount,
        method="cash",
        received_on=on,
        request_key=uuid.uuid4(),
        **extra,
    )
    if charge is not None:
        Allocation.objects.create(payment=payment, charge=charge, amount_minor=amount)
    return payment


@pytest.fixture
def world(club, staff, admin):
    """Last year's books: dues, an event fee and a welfare gift received; categorised spending, one of
    it reversed; a waived due; a due still owed; money from the year before."""
    start, end = last_year()
    treasurer = make_user("treasurer@example.com", display_name="Treasurer")
    add_member(
        club,
        treasurer,
        Role.objects.create(organization=club, name="Finance", permissions=["finances.manage"]),
    )
    member, outsider = (
        make_user("mary.member@example.com", display_name="Mary Member"),
        make_user("out@example.com"),
    )
    add_member(club, member)
    dues = Campaign.objects.create(
        organization=club, title="Operations dues", amount_minor=50000, starts_on=start
    )
    mid = start + timedelta(days=100)

    def charge(kind, amount, **extra):
        made = Charge.objects.create(
            organization=club, member=member, kind=kind, purpose="x", amount_minor=amount, **extra
        )
        Charge.objects.filter(pk=made.pk).update(created_at=timezone.now() - timedelta(days=400))
        return made

    due = charge("due", 50000, campaign=dues)
    owed = charge("due", 50000, campaign=dues)
    waived = charge("due", 30000, campaign=dues)
    Charge.objects.filter(pk=waived.pk).update(
        waived_at=timezone.make_aware(timezone.datetime(mid.year, mid.month, mid.day))
    )
    fee = charge("event_fee", 20000)
    gift = charge("welfare", 10000)
    pay(club, member, 100000, start - timedelta(days=30))  # the year before: the opening balance
    Expense.objects.create(
        organization=club, description="Old", amount_minor=40000, spent_on=start - timedelta(days=10)
    )
    pay(club, member, 50000, mid, due)
    pay(club, member, 20000, mid, owed)  # part paid: 300 still owed
    pay(club, member, 20000, mid, fee)
    pay(club, member, 10000, mid, gift)
    pay(club, member, 7000, mid)  # not matched to anything
    pay(club, member, 99900, mid, reversed_at=timezone.now())  # reversed: counts for nothing
    spend = {"organization": club, "spent_on": mid}
    Expense.objects.create(
        description="Hall for March",
        category="hall_hire",
        amount_minor=30000,
        campaign=dues,
        payee="MARK-PAYEE",
        **spend,
    )
    Expense.objects.create(
        description="Balls", category="equipment", amount_minor=45000, campaign=dues, **spend
    )
    Expense.objects.create(description="Bus", category="transport", amount_minor=15000, **spend)
    Expense.objects.create(
        description="Wrong", category="events", amount_minor=88800, reversed_at=timezone.now(), **spend
    )
    return {
        "club": club,
        "staff": staff,
        "treasurer": logged_in(treasurer),
        "member": logged_in(member),
        "outsider": logged_in(outsider),
        "anonymous": BrowserClient(),
        "users": {"member": member},
        "dues": dues,
        "mid": mid,
    }


def draft(world) -> dict:
    made = world["treasurer"].post(url(world["club"], "annual-reports/"), {}, format="json")
    assert made.status_code == 201, made.json()
    return made.json()


def report_url(world, report, tail=""):
    return url(world["club"], f"annual-reports/{report['id']}/{tail}")


def test_expenses_carry_a_category_and_a_payee(world):
    club = world["club"]
    made = world["treasurer"].post(
        url(club, "finance/expenses/"),
        {
            "description": "Nets",
            "category": "equipment",
            "payee": "Sports House",
            "amount_minor": 12000,
            "spent_on": str(world["mid"]),
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    assert (made.json()["category"], made.json()["payee"]) == ("equipment", "Sports House")
    plain = (
        world["treasurer"]
        .post(
            url(club, "finance/expenses/"),
            {"description": "Tea", "amount_minor": 500, "spent_on": str(world["mid"])},
            format="json",
        )
        .json()
    )
    assert plain["category"] == "other"
    bad = {"description": "x", "category": "bribes", "amount_minor": 1, "spent_on": str(world["mid"])}
    assert world["treasurer"].post(url(club, "finance/expenses/"), bad, format="json").status_code == 400


def test_the_financial_year_end_is_set_by_finance_managers(world):
    club = world["club"]
    assert world["treasurer"].get(url(club, "finance/settings/")).json() == {
        "year_end_month": 12,
        "year_end_day": 31,
    }
    assert world["member"].get(url(club, "finance/settings/")).status_code == 403
    assert (
        world["member"]
        .put(url(club, "finance/settings/"), {"year_end_month": 6, "year_end_day": 30}, format="json")
        .status_code
        == 403
    )
    for bad in (
        {"year_end_month": 2, "year_end_day": 30},
        {"year_end_month": 13, "year_end_day": 1},
        {"year_end_month": 6, "year_end_day": 30, "x": 1},
    ):
        assert world["treasurer"].put(url(club, "finance/settings/"), bad, format="json").status_code == 400
    assert (
        world["treasurer"]
        .put(url(club, "finance/settings/"), {"year_end_month": 6, "year_end_day": 30}, format="json")
        .status_code
        == 200
    )
    start, end = reports.period_ending(club, date(2026, 11, 25))
    assert (start, end) == (date(2025, 7, 1), date(2026, 6, 30))
    assert reports.period_ending(club, date(2026, 6, 29)) == (date(2024, 7, 1), date(2025, 6, 30))


def test_the_draft_reconciles_with_the_ledger(world):
    start, end = last_year()
    report = draft(world)
    assert (report["period_start"], report["period_end"], report["status"], report["version"]) == (
        str(start),
        str(end),
        "draft",
        1,
    )
    kes = report["figures"]["currencies"][0]
    assert kes["opening_minor"] == 100000 - 40000
    assert kes["receipts_minor"] == 50000 + 20000 + 20000 + 10000 + 7000
    assert {r["label"]: r["amount_minor"] for r in kes["receipts"]} == {
        "Dues and campaigns": 70000,
        "Welfare projects": 10000,
        "Event fees": 20000,
        "Not yet matched to a charge": 7000,
    }
    assert kes["expenses_minor"] == 30000 + 45000 + 15000
    assert {r["label"]: r["amount_minor"] for r in kes["expenses"]} == {
        "Equipment": 45000,
        "Hall hire": 30000,
        "Transport": 15000,
    }
    # Opening + receipts - expenses = closing, exactly.
    assert (
        kes["closing_minor"] == kes["opening_minor"] + kes["receipts_minor"] - kes["expenses_minor"] == 77000
    )
    # The same as adding up the ledger directly.
    standing = Payment.objects.filter(
        organization=world["club"], reversed_at__isnull=True, received_on__lte=end
    )
    spent = Expense.objects.filter(organization=world["club"], reversed_at__isnull=True, spent_on__lte=end)
    assert kes["closing_minor"] == sum(p.amount_minor for p in standing) - sum(e.amount_minor for e in spent)
    assert kes["outstanding_dues_minor"] == 30000 and kes["waived_minor"] == 30000
    # The dues campaign took 700 and spent 750: a deficit, shown negative.
    purposes = {p["title"]: p for p in kes["purposes"]}
    assert purposes["Operations dues"]["net_minor"] == 70000 - 75000 == -5000
    assert purposes["General"]["spent_minor"] == 15000

    # One report a year; a year still running has none.
    again = world["treasurer"].post(url(world["club"], "annual-reports/"), {}, format="json")
    assert again.status_code == 409 and again.json()["code"] == "report_exists"
    this_year = {"period_end": f"{timezone.localdate().year}-12-31"}
    running = world["treasurer"].post(url(world["club"], "annual-reports/"), this_year, format="json")
    assert running.status_code == 409 and running.json()["code"] == "year_not_over"
    odd = world["treasurer"].post(
        url(world["club"], "annual-reports/"), {"period_end": "2024-06-30"}, format="json"
    )
    assert odd.status_code == 400


def test_who_reads_a_report_and_what_it_never_shows(world):
    club = world["club"]
    report = draft(world)
    listing = url(club, "annual-reports/")
    # A draft is for finance staff.
    assert (
        world["member"].get(listing).json() == []
        and world["member"].get(report_url(world, report)).status_code == 404
    )
    assert world["member"].post(listing, {}, format="json").status_code == 403
    for action in ("publish/", "amend/"):
        assert world["member"].post(report_url(world, report, action), {}, format="json").status_code == 403
    world["treasurer"].patch(report_url(world, report), {"narrative": "A steady year."}, format="json")
    published = world["treasurer"].post(report_url(world, report, "publish/"), {}, format="json").json()
    assert published["status"] == "published" and published["published_at"]

    # Members read it; outsiders and the public don't until it is made public.
    seen = world["member"].get(report_url(world, report))
    assert seen.status_code == 200 and seen.json()["narrative"] == "A steady year."
    assert seen.json()["can_edit"] is False and seen.json()["published_by_name"] is None
    for other in ("outsider", "anonymous"):
        assert world[other].get(listing).json() == []
        assert world[other].get(report_url(world, report)).status_code == 404
        assert world[other].get(report_url(world, report, "export.csv")).status_code == 404
    assert (
        world["member"].patch(report_url(world, report), {"public": True}, format="json").status_code == 403
    )
    assert (
        world["treasurer"].patch(report_url(world, report), {"public": True}, format="json").json()["public"]
        is True
    )
    for other in ("outsider", "anonymous"):
        assert [r["id"] for r in world[other].get(listing).json()] == [report["id"]]
        assert world[other].get(report_url(world, report)).status_code == 200
    assert world["anonymous"].post(listing, {}, format="json").status_code == 401

    # Aggregates only: no member, payer, payee or receipt, in the page or the files.
    body = world["anonymous"].get(report_url(world, report)).content.decode()
    files = world["anonymous"].get(report_url(world, report, "export.csv")).content.decode()
    for private in (
        "Mary Member",
        "mary.member@example.com",
        str(world["users"]["member"].id),
        "MARK-PAYEE",
        "Hall for March",
        "Treasurer",
    ):
        assert private not in body and private not in files, private


def test_a_published_report_is_frozen_and_corrected_by_an_amendment(world):
    club = world["club"]
    report = draft(world)
    assert (
        world["treasurer"].post(report_url(world, report, "amend/"), {}, format="json").json()["code"]
        == "not_published"
    )
    first = world["treasurer"].post(report_url(world, report, "publish/"), {}, format="json").json()
    assert (
        world["treasurer"].post(report_url(world, report, "publish/"), {}, format="json").json()["code"]
        == "report_published"
    )
    assert (
        world["treasurer"].patch(report_url(world, report), {"narrative": "x"}, format="json").json()["code"]
        == "report_published"
    )
    assert world["treasurer"].delete(report_url(world, report)).json()["code"] == "report_published"

    # A correction dated in the reported year: an expense that was missed.
    Expense.objects.create(
        organization=club,
        description="Late invoice",
        category="hall_hire",
        amount_minor=10000,
        spent_on=world["mid"],
    )
    unchanged = world["treasurer"].get(report_url(world, report)).json()
    assert unchanged["figures"] == first["figures"]  # the published figures don't move

    amended = world["treasurer"].post(report_url(world, report, "amend/"), {}, format="json")
    assert amended.status_code == 201, amended.json()
    second = amended.json()
    assert (second["version"], second["status"], second["amends"]) == (2, "draft", report["id"])
    assert (
        world["treasurer"].post(report_url(world, report, "amend/"), {}, format="json").json()["code"]
        == "already_amended"
    )
    out = world["treasurer"].post(report_url(world, second, "publish/"), {}, format="json").json()
    kes = out["figures"]["currencies"][0]
    assert kes["expenses_minor"] == 100000 and kes["closing_minor"] == 67000
    assert "Expenses (KES): 900.00 became 1,000.00" in out["changes"]
    assert "Expenses: Hall hire (KES): 300.00 became 400.00" in out["changes"]
    assert "Closing balance (KES): 770.00 became 670.00" in out["changes"]
    # Both versions stay, the original as it was.
    versions = world["member"].get(url(club, "annual-reports/")).json()
    assert [(v["version"], v["figures"]["currencies"][0]["closing_minor"]) for v in versions] == [
        (2, 67000),
        (1, 77000),
    ]
    assert AnnualReport.objects.get(pk=report["id"]).snapshot == first["figures"]


def test_the_report_exports_as_csv_and_pdf(world):
    report = draft(world)
    world["treasurer"].patch(
        report_url(world, report), {"narrative": "=SUM(A1:A9) was a steady year."}, format="json"
    )
    world["treasurer"].post(report_url(world, report, "publish/"), {}, format="json")
    response = world["member"].get(report_url(world, report, "export.csv"))
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    rows = {row[0]: row[1] for row in csv.reader(io.StringIO(response.content.decode())) if len(row) == 2}
    assert rows["Total receipts"] == "1,070.00" and rows["Total expenses"] == "900.00"
    assert rows["Closing balance (KES)"] == "770.00" and rows["Operations dues"] == "-50.00"
    assert "'=SUM(A1:A9) was a steady year." in rows  # a spreadsheet won't run it
    pdf = world["member"].get(report_url(world, report, "export.pdf"))
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-1.4") and pdf.content.rstrip().endswith(b"%%EOF")
    assert b"Closing balance" in pdf.content and b"770.00" in pdf.content
    # A draft can be thrown away; a published one can't (covered above).
    assert world["outsider"].get(report_url(world, report, "export.pdf")).status_code == 404
