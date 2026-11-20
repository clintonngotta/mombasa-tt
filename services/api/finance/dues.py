"""Contribution campaigns and their dues (REQ-023, TASK-038).

A campaign's periods fall on its start date and then every week, month, quarter or year after it. Each
period's due is a charge in the REQ-022 ledger, made once per member and period whatever runs the
generator (the database refuses a second), with the amount as it stood when it was made.

Who owes a period: an active member (all members, or those selected) who isn't waived from the
campaign, and who was a member when the campaign was set up or joined before the period's date, so a new
member starts with the next period after joining and never owes earlier ones. A member who leaves owes
no later periods and keeps the earlier dues.
"""

import calendar
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from organizations.committee import local_today
from organizations.models import Membership

from . import ledger
from .models import Campaign, Charge

MONTHS = {Campaign.Cadence.MONTHLY: 1, Campaign.Cadence.QUARTERLY: 3, Campaign.Cadence.YEARLY: 12}


def add_months(day: date, months: int, anchor_day: int) -> date:
    years, month = divmod(day.month - 1 + months, 12)
    year = day.year + years
    return date(year, month + 1, min(anchor_day, calendar.monthrange(year, month + 1)[1]))


def period_on(campaign: Campaign, n: int) -> date:
    """The n-th period's date, counted from the start each time so a clamped month doesn't drift."""
    start = campaign.starts_on
    if campaign.cadence == Campaign.Cadence.WEEKLY:
        return start + timedelta(weeks=n)
    return add_months(start, MONTHS.get(campaign.cadence, 0) * n, start.day)


def periods(campaign: Campaign, until: date):
    """The periods due by `until`, oldest first."""
    last = min(until, campaign.ends_on) if campaign.ends_on else until
    n = 0
    while True:
        day = period_on(campaign, n)
        if day > last:
            return
        yield day
        if campaign.cadence == Campaign.Cadence.ONCE:
            return
        n += 1


def next_period(campaign: Campaign, today: date) -> date | None:
    if campaign.closed_at:
        return None
    for n in range(0, 100_000):
        day = period_on(campaign, n)
        if campaign.ends_on and day > campaign.ends_on:
            return None
        if day > today:
            return day
        if campaign.cadence == Campaign.Cadence.ONCE:
            return None
    return None


def _owing(campaign: Campaign):
    """(member, amount, joined date, there at the start) for each active member the campaign bills."""
    zone = ZoneInfo(campaign.organization.timezone)
    terms = {t.member_id: t for t in campaign.terms.all()}
    for membership in Membership.objects.active().filter(organization_id=campaign.organization_id):
        term = terms.get(membership.user_id)
        if campaign.audience == Campaign.Audience.SELECTED and not (term and term.included):
            continue
        if term and term.waived:
            continue
        amount = term.amount_minor if term and term.amount_minor is not None else campaign.amount_minor
        joined = timezone.localdate(membership.joined_at, zone)
        yield membership.user_id, amount, joined, membership.joined_at <= campaign.created_at


@transaction.atomic
def generate(campaign: Campaign, today: date) -> int:
    """Make every due that has fallen by `today` and isn't made yet. Running it again, or twice at once,
    makes nothing new. Returns how many it made."""
    if campaign.closed_at:
        return 0
    owing = list(_owing(campaign))
    made = []
    for day in periods(campaign, today):
        for member_id, amount, joined, founding in owing:
            if amount == 0 or not (founding or joined < day):
                continue
            made.append(
                Charge(
                    organization_id=campaign.organization_id,
                    member_id=member_id,
                    kind=Charge.Kind.DUE,
                    purpose=campaign.title,
                    amount_minor=amount,
                    currency=campaign.currency,
                    due_on=day,
                    campaign=campaign,
                    period=day,
                    created_by=campaign.created_by,
                )
            )
    before = campaign.dues.count()
    Charge.objects.bulk_create(made, ignore_conflicts=True)
    return campaign.dues.count() - before


def outstanding_dues(queryset, today: date):
    """(due, what is left, status) for each campaign due that still owes something by `today`."""
    for charge in queryset.filter(campaign__isnull=False, waived_at__isnull=True, due_on__lte=today):
        left = ledger.outstanding(charge)
        if left > 0:
            yield charge, left, ledger.status(charge, today)


def remind(organization, today: date) -> int:
    """Tell each member of a due falling today, and once more when it passes unpaid. Sending again on
    the same day, or any day after, repeats nothing."""
    from notifications import triggers

    dues = Charge.objects.filter(organization=organization).select_related("organization")
    return sum(
        triggers.due_reminder(charge, "due" if charge.due_on == today else "overdue", left)
        for charge, left, _ in outstanding_dues(dues, today)
    )


def nudge(campaign: Campaign, today: date) -> int:
    """Staff remind everyone overdue on the campaign; at most once a day each."""
    from notifications import triggers

    dues = campaign.dues.select_related("organization")
    return sum(
        triggers.due_reminder(charge, "overdue", left, version=f"nudge:{today.isoformat()}")
        for charge, left, state in outstanding_dues(dues, today)
        if state == "overdue"
    )


def catch_up(organization, today: date | None = None) -> int:
    """Generate every open campaign's dues to date: on reading the ledger and from `generate_dues`."""
    today = today or local_today(organization)
    return sum(
        generate(campaign, today)
        for campaign in organization.campaigns.filter(closed_at__isnull=True).select_related("organization")
    )
