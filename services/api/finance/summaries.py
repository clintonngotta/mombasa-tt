"""Where the money came from and went (REQ-024, TASK-040).

Received is what standing payments were actually matched to a purpose's charges, never what is still
expected. Spent is the purpose's expenses that stand. Remaining is received less spent, and goes negative
when more was spent than received: a deficit is shown, never covered by invented funds. Expected (dues not
yet paid) is reported apart.
"""

from collections import defaultdict

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.permissions import Permission

from . import ledger
from .models import Allocation, Campaign, Charge, Expense

STANDING_ALLOCATION = Q(payment__reversed_at__isnull=True)
STANDING_EXPENSE = Q(reversed_at__isnull=True)
GENERAL = None  # expenses and receipts not tied to a campaign


def purpose_totals(organization, *, campaigns_only=False) -> list[dict]:
    """One row per purpose and currency: received, spent, remaining and still expected."""
    rows = defaultdict(lambda: {"received_minor": 0, "spent_minor": 0, "expected_minor": 0})
    received = (
        Allocation.objects.filter(STANDING_ALLOCATION, charge__organization=organization)
        # Welfare projects keep their own totals, the dues of a required one included.
        .exclude(charge__kind=Charge.Kind.WELFARE)
        .exclude(charge__campaign__welfare_project__isnull=False)
        .values("charge__campaign_id", "charge__currency")
        .annotate(total=Sum("amount_minor"))
    )
    for r in received:
        rows[(r["charge__campaign_id"], r["charge__currency"])]["received_minor"] += r["total"]
    spent = (
        Expense.objects.filter(STANDING_EXPENSE, organization=organization, welfare_project__isnull=True)
        .values("campaign_id", "currency")
        .annotate(total=Sum("amount_minor"))
    )
    for r in spent:
        rows[(r["campaign_id"], r["currency"])]["spent_minor"] += r["total"]
    for charge in (
        Charge.objects.filter(organization=organization, campaign__isnull=False, waived_at__isnull=True)
        .exclude(campaign__welfare_project__isnull=False)
        .prefetch_related("allocations__payment")
    ):
        left = ledger.outstanding(charge)
        if left:
            rows[(charge.campaign_id, charge.currency)]["expected_minor"] += left
    titles = {}
    for campaign_id, title, currency in Campaign.objects.filter(
        organization=organization, welfare_project__isnull=True
    ).values_list("id", "title", "currency"):
        titles[campaign_id] = title
        if not any(key[0] == campaign_id for key in rows):
            rows[(campaign_id, currency)]  # every campaign shows, even before money moves
    out = []
    for (campaign_id, currency), totals in rows.items():
        if campaigns_only and campaign_id is GENERAL:
            continue
        out.append(
            {
                "campaign_id": campaign_id,
                "title": titles.get(campaign_id, "General"),
                "currency": currency,
                **totals,
                "remaining_minor": totals["received_minor"] - totals["spent_minor"],
            }
        )
    return sorted(out, key=lambda r: (r["campaign_id"] is None, r["title"].lower(), r["currency"]))


def check_campaign(organization, campaign_id) -> Campaign | None:
    if campaign_id is None:
        return None
    # A required welfare project's spending goes on the project itself.
    campaign = Campaign.objects.filter(
        organization=organization, pk=campaign_id, welfare_project__isnull=True
    ).first()
    if campaign is None:
        raise ApiException("bad_campaign", "Choose one of the organization's campaigns.", 400)
    return campaign


@transaction.atomic
def reverse_expense(expense: Expense, actor, reason: str) -> Expense:
    expense = Expense.objects.select_for_update().get(pk=expense.pk)
    if expense.reversed_at:
        raise ApiException("already_reversed", "This expense was already reversed.", 409)
    expense.reversed_at = timezone.now()
    expense.reversed_by = actor
    expense.reversal_reason = reason
    expense.save(update_fields=["reversed_at", "reversed_by", "reversal_reason"])
    return expense


def can_read_receipt(user, attachment) -> bool:
    """Finance staff of the organization whose expense it is; nobody else, the uploader included once
    they no longer hold the permission."""
    expense = Expense.objects.filter(receipt=attachment).select_related("organization").first()
    if expense is None:
        return False
    held = effective_permissions(user, expense.organization)
    return bool(held & {Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE})
