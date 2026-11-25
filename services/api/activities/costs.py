"""Sharing an activity's cost (REQ-039 Phase 2, TASK-075).

Staff holding both activities.manage and finances.manage bill the members going (with a place, not
waitlisted) through a one-time REQ-023 campaign: a set amount each, or a total split evenly and rounded
up to the next whole unit. Spending is a REQ-024 expense on that campaign, so received, spent and
remaining reconcile like any purpose. Someone who answers going later is added by finance staff through
the campaign's terms; Coast TT never collects the money itself.
"""

from django.db import transaction
from django.db.models import Sum

from core.exceptions import ApiException
from finance import dues, ledger
from finance.models import Allocation, Campaign, CampaignMember

from .models import Activity, Rsvp

WELFARE_TITLE = "Welfare visit share"


def going_ids(activity: Activity) -> list:
    return list(
        activity.rsvps.filter(answer=Rsvp.Answer.GOING, waitlisted=False).values_list("user_id", flat=True)
    )


@transaction.atomic
def share(activity: Activity, actor, today, *, due_on, amount_minor=None, total_minor=None, currency="KES"):
    activity = Activity.objects.select_for_update().select_related("organization").get(pk=activity.pk)
    if activity.status != Activity.Status.PUBLISHED:
        raise ApiException("activity_closed", "Share the cost of a published activity.", 409)
    if activity.audience not in (Activity.Audience.MEMBERS, Activity.Audience.SELECTED):
        raise ApiException("members_only", "Only an activity for members can share its cost.", 409)
    if activity.campaign_id:
        raise ApiException("already_shared", "This activity's cost is already shared.", 409)
    if (amount_minor is None) == (total_minor is None):
        raise ApiException("amount_or_total", "Give an amount each or a total to split.", 400)
    if due_on < today:
        raise ApiException("due_in_past", "The due date can't be in the past.", 400)
    going = going_ids(activity)
    if not going:
        raise ApiException("nobody_going", "Nobody is going yet.", 409)
    if total_minor is not None:
        # Split in whole units (KES, not cents), rounded up so the total is covered.
        each_unit = -(-total_minor // (100 * len(going)))
        amount_minor = each_unit * 100
    campaign = Campaign.objects.create(
        organization=activity.organization,
        # A welfare visit's share says nothing about whom it is for (REQ-038).
        title=WELFARE_TITLE if activity.welfare_project_id else activity.title[:120],
        amount_minor=amount_minor,
        currency=currency,
        cadence=Campaign.Cadence.ONCE,
        starts_on=due_on,
        ends_on=due_on,
        audience=Campaign.Audience.SELECTED,
        created_by=actor,
    )
    CampaignMember.objects.bulk_create(CampaignMember(campaign=campaign, member_id=pk) for pk in going)
    activity.campaign = campaign
    activity.save(update_fields=["campaign"])
    dues.generate(campaign, today)
    return activity


def summary(activity: Activity, user, today, *, staff: bool) -> dict | None:
    """What each pays and the viewer's own share for the audience; the purpose totals for finance
    staff only."""
    if not activity.campaign_id:
        return None
    campaign = activity.campaign
    mine = campaign.dues.filter(member=user, waived_at__isnull=True).first()
    out = {
        "amount_minor": campaign.amount_minor,
        "currency": campaign.currency,
        "due_on": campaign.starts_on,
        "my_share": None,
        "received_minor": None,
        "spent_minor": None,
        "remaining_minor": None,
    }
    if mine:
        out["my_share"] = {
            "outstanding_minor": ledger.outstanding(mine),
            "status": ledger.status(mine, today),
        }
    if staff:
        received = (
            Allocation.objects.filter(charge__campaign=campaign, payment__reversed_at__isnull=True).aggregate(
                t=Sum("amount_minor")
            )["t"]
            or 0
        )
        spent = campaign.expenses.filter(reversed_at__isnull=True).aggregate(t=Sum("amount_minor"))["t"] or 0
        out.update(received_minor=received, spent_minor=spent, remaining_minor=received - spent)
    return out
