"""The annual financial report (REQ-041): the figures of one financial year, straight from the ledger.

Cash basis: a receipt counts on the day the payment was received, spending on the day it was spent.
Reversed payments and expenses count for nothing, whenever they were reversed; that is why a published
report keeps its own frozen figures. Everything is totalled per currency and nothing names a member.
"""

import calendar
import csv
import io
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Q, Sum

from core.pdf import text_pdf

from .models import Allocation, Charge, Expense, FinanceSettings, Payment

STANDING = Q(reversed_at__isnull=True)
RECEIPT_GROUPS = [
    "Dues and campaigns",
    "Welfare projects",
    "Event fees",
    "Other",
    "Not yet matched to a charge",
]


def year_end(organization) -> tuple[int, int]:
    settings = FinanceSettings.objects.filter(organization=organization).first()
    return (settings.year_end_month, settings.year_end_day) if settings else (12, 31)


def _on(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def period_ending(organization, on_or_before: date) -> tuple[date, date]:
    """The latest financial year that had ended by `on_or_before`: (first day, last day)."""
    month, day = year_end(organization)
    end = _on(on_or_before.year, month, day)
    if end > on_or_before:
        end = _on(on_or_before.year - 1, month, day)
    return _on(end.year - 1, month, day) + timedelta(days=1), end


def period_for(organization, end: date) -> tuple[date, date]:
    """The financial year ending on `end`, which must be a year end of the organization."""
    month, day = year_end(organization)
    if end != _on(end.year, month, day):
        raise ValueError("not a year end")
    return _on(end.year - 1, month, day) + timedelta(days=1), end


def _group(kind: str, campaign_id, welfare_campaign: bool) -> str:
    if kind == Charge.Kind.WELFARE or welfare_campaign:
        return "Welfare projects"
    if kind == Charge.Kind.EVENT_FEE:
        return "Event fees"
    if kind == Charge.Kind.DUE or campaign_id:
        return "Dues and campaigns"
    return "Other"


def _sum(queryset) -> dict:
    return {
        row["currency"]: row["total"]
        for row in queryset.values("currency").annotate(total=Sum("amount_minor"))
    }


def figures(organization, start: date, end: date) -> dict:
    """The year's figures per currency. Opening + receipts - expenses = closing, to the cent."""
    payments = Payment.objects.filter(STANDING, organization=organization)
    expenses = Expense.objects.filter(STANDING, organization=organization)
    in_year = Q(received_on__gte=start, received_on__lte=end)
    spent_in_year = Q(spent_on__gte=start, spent_on__lte=end)
    opening_in, opening_out = (
        _sum(payments.filter(received_on__lt=start)),
        _sum(expenses.filter(spent_on__lt=start)),
    )
    received = _sum(payments.filter(in_year))
    spent = _sum(expenses.filter(spent_in_year))

    receipts: dict = defaultdict(lambda: defaultdict(int))
    purposes: dict = defaultdict(lambda: defaultdict(lambda: {"received_minor": 0, "spent_minor": 0}))
    matched: dict = defaultdict(int)
    allocations = (
        Allocation.objects.filter(
            payment__organization=organization,
            payment__reversed_at__isnull=True,
            payment__received_on__gte=start,
            payment__received_on__lte=end,
        )
        .values(
            "payment__currency",
            "charge__kind",
            "charge__campaign_id",
            "charge__campaign__title",
            "charge__campaign__welfare_project",
        )
        .annotate(total=Sum("amount_minor"))
    )
    for row in allocations:
        currency = row["payment__currency"]
        welfare = row["charge__campaign__welfare_project"] is not None
        group = _group(row["charge__kind"], row["charge__campaign_id"], welfare)
        receipts[currency][group] += row["total"]
        matched[currency] += row["total"]
        if row["charge__campaign_id"]:
            purposes[currency][row["charge__campaign__title"]]["received_minor"] += row["total"]
    by_category: dict = defaultdict(lambda: defaultdict(int))
    labels = dict(Expense.Category.choices)
    spending = (
        expenses.filter(spent_in_year)
        .values("currency", "category", "campaign__title", "welfare_project__title")
        .annotate(total=Sum("amount_minor"))
    )
    for row in spending:
        by_category[row["currency"]][labels.get(row["category"], "Other")] += row["total"]
        title = row["campaign__title"] or (
            f"Welfare: {row['welfare_project__title']}" if row["welfare_project__title"] else "General"
        )
        purposes[row["currency"]][title]["spent_minor"] += row["total"]

    # Dues still owed at the year end, and what was waived during the year: totals only.
    outstanding: dict = defaultdict(int)
    waived: dict = defaultdict(int)
    charges = Charge.objects.filter(organization=organization, created_at__date__lte=end).prefetch_related(
        "allocations__payment"
    )
    for charge in charges.iterator(chunk_size=500):
        paid = sum(
            a.amount_minor
            for a in charge.allocations.all()
            if a.payment.reversed_at is None and a.payment.received_on <= end
        )
        left = charge.amount_minor - paid
        if left <= 0:
            continue
        waived_on = charge.waived_at.date() if charge.waived_at else None
        if waived_on and waived_on <= end:
            if waived_on >= start:
                waived[charge.currency] += left
            continue
        outstanding[charge.currency] += left

    currencies = sorted(
        set(opening_in) | set(opening_out) | set(received) | set(spent) | set(outstanding) | set(waived)
    ) or ["KES"]
    out = []
    for currency in currencies:
        opening = opening_in.get(currency, 0) - opening_out.get(currency, 0)
        got, gone = received.get(currency, 0), spent.get(currency, 0)
        groups = dict(receipts[currency])
        unmatched = got - matched[currency]
        if unmatched:
            groups["Not yet matched to a charge"] = unmatched
        rows = [
            {"title": title, **totals, "net_minor": totals["received_minor"] - totals["spent_minor"]}
            for title, totals in sorted(purposes[currency].items())
        ]
        out.append(
            {
                "currency": currency,
                "opening_minor": opening,
                "receipts_minor": got,
                "receipts": [
                    {"label": label, "amount_minor": groups[label]}
                    for label in RECEIPT_GROUPS
                    if groups.get(label)
                ],
                "expenses_minor": gone,
                "expenses": [
                    {"label": label, "amount_minor": amount}
                    for label, amount in sorted(by_category[currency].items())
                ],
                "purposes": rows,  # a negative net is a deficit
                "closing_minor": opening + got - gone,
                "outstanding_dues_minor": outstanding.get(currency, 0),
                "waived_minor": waived.get(currency, 0),
            }
        )
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "currencies": out}


def money(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100:,}.{abs(minor) % 100:02d}"


def differences(before: dict, after: dict) -> list[str]:
    """What an amended version changes, line by line, in words."""

    def flat(snapshot: dict) -> dict:
        lines = {}
        for block in snapshot.get("currencies", []):
            c = block["currency"]
            for key, label in (
                ("opening_minor", "Opening balance"),
                ("receipts_minor", "Receipts"),
                ("expenses_minor", "Expenses"),
                ("closing_minor", "Closing balance"),
                ("outstanding_dues_minor", "Outstanding dues"),
                ("waived_minor", "Waived"),
            ):
                lines[f"{label} ({c})"] = block[key]
            for row in block["receipts"]:
                lines[f"Receipts: {row['label']} ({c})"] = row["amount_minor"]
            for row in block["expenses"]:
                lines[f"Expenses: {row['label']} ({c})"] = row["amount_minor"]
        return lines

    old, new = flat(before), flat(after)
    return [
        f"{label}: {money(old.get(label, 0))} became {money(new.get(label, 0))}"
        for label in sorted(set(old) | set(new))
        if old.get(label, 0) != new.get(label, 0)
    ]


def _cell(value) -> str:
    """A spreadsheet runs a cell that starts with one of these as a formula: make it text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text) else text


def _is_number(text: str) -> bool:
    try:
        float(text.replace(",", ""))
    except ValueError:
        return False
    return True


def lines(organization_name: str, report, snapshot: dict) -> list[tuple[str, str]]:
    """The report as (label, amount) rows, shared by the CSV and the PDF."""
    out = [
        (organization_name, ""),
        (f"Financial report, {snapshot['period_start']} to {snapshot['period_end']}", ""),
        (f"Version {report.version}" + ("" if report.status == "published" else " (draft)"), ""),
    ]
    for block in snapshot["currencies"]:
        c = block["currency"]
        out += [("", ""), (f"Opening balance ({c})", money(block["opening_minor"])), ("Receipts", "")]
        out += [(f"  {row['label']}", money(row["amount_minor"])) for row in block["receipts"]]
        out += [("Total receipts", money(block["receipts_minor"])), ("Expenses", "")]
        out += [(f"  {row['label']}", money(row["amount_minor"])) for row in block["expenses"]]
        out += [("Total expenses", money(block["expenses_minor"]))]
        out += [(f"Closing balance ({c})", money(block["closing_minor"]))]
        out += [("Outstanding dues at the year end", money(block["outstanding_dues_minor"]))]
        out += [("Dues waived in the year", money(block["waived_minor"]))]
        if block["purposes"]:
            out += [("By purpose: received less spent (a minus is a deficit)", "")]
            out += [(f"  {row['title']}", money(row["net_minor"])) for row in block["purposes"]]
    if report.changes:
        out += [("", ""), ("Changes from the version before", "")]
        out += [(f"  {change}", "") for change in report.changes]
    if report.narrative:
        out += [("", ""), ("Summary", "")]
        out += [(f"  {line}", "") for line in report.narrative.splitlines() if line.strip()]
    return out


def as_csv(rows: list[tuple[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Item", "Amount"])
    for label, amount in rows:
        writer.writerow([_cell(label.strip()), amount])
    return out.getvalue()


def as_pdf(rows: list[tuple[str, str]]) -> bytes:
    """The same rows as a plain PDF: the label, and the amount in a column on the right."""
    return text_pdf([f"{label[:78]:<80}{amount:>16}" if amount else label for label, amount in rows])
