"""Welfare projects (REQ-038, TASK-074): voluntary giving to a shared cause, through the manual ledger.

A contribution is money received (a REQ-022 payment) matched in full to a paid welfare charge, so it
never leaves anyone owing: there is no overdue status for not giving. Spending is a REQ-024 expense on
the project. Received, spent and remaining reconcile the same way as any purpose, deficits included.

Staff can make giving required (TASK-075): the project then gets a one-time REQ-023 campaign whose dues
fall on one date for its audience, the beneficiary excepted. Payments matched to those dues count towards
the project like gifts, and only then can anyone be overdue. A planned visit is a REQ-039 activity linked
to the project.
"""

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.models import Membership
from organizations.permissions import Permission

from . import dues, ledger
from .models import Allocation, Campaign, CampaignMember, Charge, Expense, WelfareContribution, WelfareProject

STAFF = {Permission.WELFARE_MANAGE, Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE}
RECORDERS = {Permission.WELFARE_MANAGE, Permission.FINANCES_MANAGE}


def is_staff(user, organization) -> bool:
    return bool(effective_permissions(user, organization) & STAFF)


def can_record(user, organization) -> bool:
    return bool(effective_permissions(user, organization) & RECORDERS)


def is_closed(project: WelfareProject, today) -> bool:
    """Closed by staff, or past its deadline. A closed project is read-only."""
    return project.closed_at is not None or bool(project.deadline and project.deadline < today)


def visible_to_member(project: WelfareProject, user) -> bool:
    """In the audience (all active members, or those chosen) and not hidden at the beneficiary's
    request. The beneficiary sees it like anyone in the audience until it is hidden."""
    if project.hidden_at:
        return False
    if not Membership.objects.active().filter(organization=project.organization, user=user).exists():
        return False
    if project.audience == WelfareProject.Audience.SELECTED:
        return project.audience_members.filter(pk=user.pk).exists() or project.beneficiary_id == user.pk
    return True


def _towards(project: WelfareProject) -> Q:
    """Charges whose payments count towards the project: its gifts and, once required, its dues."""
    towards = Q(charge__welfare__project=project)
    if project.campaign_id:
        towards |= Q(charge__campaign_id=project.campaign_id)
    return towards


def totals(project: WelfareProject) -> dict:
    received = (
        Allocation.objects.filter(_towards(project), payment__reversed_at__isnull=True).aggregate(
            total=Sum("amount_minor")
        )["total"]
        or 0
    )
    spent = (
        project.expenses.filter(reversed_at__isnull=True).aggregate(total=Sum("amount_minor"))["total"] or 0
    )
    return {"received_minor": received, "spent_minor": spent, "remaining_minor": received - spent}


def own_total(project: WelfareProject, user) -> int:
    """What the member gave or paid towards the project."""
    return (
        Allocation.objects.filter(
            _towards(project), charge__member=user, payment__reversed_at__isnull=True
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )


def expected_total(project: WelfareProject) -> int:
    """Dues of a required project not paid yet; nothing while giving is voluntary."""
    if not project.campaign_id:
        return 0
    charges = project.campaign.dues.filter(waived_at__isnull=True).prefetch_related("allocations__payment")
    return sum(ledger.outstanding(charge) for charge in charges)


def own_due(project: WelfareProject, user, today) -> dict | None:
    """The member's due on a required project: its amount, what is left and its status."""
    if not project.campaign_id or user is None:
        return None
    charge = project.campaign.dues.filter(member=user, waived_at__isnull=True).first()
    if charge is None:
        return None
    return {
        "amount_minor": charge.amount_minor,
        "outstanding_minor": ledger.outstanding(charge),
        "due_on": charge.due_on,
        "status": ledger.status(charge, today),
    }


def contributor_list(project: WelfareProject) -> list[dict]:
    """Who gave, when the club shows it: anonymous givers as "Anonymous", reversed gifts left out."""
    rows = []
    for c in project.contributions.filter(payment__reversed_at__isnull=True).select_related(
        "contributor", "payment"
    ):
        rows.append(
            {
                "name": "Anonymous" if c.anonymous else c.contributor.display_name,
                "amount_minor": c.payment.amount_minor,
            }
        )
    return rows


def _open(project: WelfareProject, today) -> None:
    if is_closed(project, today):
        raise ApiException("project_closed", "This project is closed.", 409)


@transaction.atomic
def contribute(project, actor, today, *, contributor, anonymous, request_key, **money) -> WelfareContribution:
    """Record a gift. The same request again returns the first, recording nothing new."""
    project = WelfareProject.objects.select_for_update().get(pk=project.pk)
    existing = WelfareContribution.objects.filter(
        payment__organization=project.organization, payment__request_key=request_key
    ).first()
    if existing:
        return existing
    _open(project, today)
    if money["currency"] != project.currency:
        raise ApiException("currency_mismatch", "The project is kept in another currency.", 400)
    payment, _ = ledger.record(
        project.organization, actor, payer=contributor, request_key=request_key, **money
    )
    charge = Charge.objects.create(
        organization=project.organization,
        member=contributor,
        kind=Charge.Kind.WELFARE,
        purpose=project.title,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        due_on=payment.received_on,
        source_id=payment.id,
        created_by=actor,
    )
    ledger.allocate(payment, charge, payment.amount_minor, actor)
    return WelfareContribution.objects.create(
        project=project, contributor=contributor, payment=payment, charge=charge, anonymous=anonymous
    )


@transaction.atomic
def reverse_contribution(contribution: WelfareContribution, actor, reason: str, today) -> None:
    _open(contribution.project, today)
    ledger.reverse(contribution.payment, actor, reason)
    ledger.waive(contribution.charge, actor, reason)


def spend(project, actor, today, **data) -> Expense:
    _open(project, today)
    if data["currency"] != project.currency:
        raise ApiException("currency_mismatch", "The project is kept in another currency.", 400)
    return Expense.objects.create(
        organization=project.organization, welfare_project=project, recorded_by=actor, **data
    )


DUE_TITLE = "Welfare project due"


@transaction.atomic
def make_due(project: WelfareProject, actor, today, *, amount_minor: int, due_on) -> WelfareProject:
    """Make giving required (REQ-038 "unless staff explicitly make the project a due"): a one-time
    campaign for the project's audience, the beneficiary waived. Its title is neutral, since reminders
    and the member's dues list show it: nothing about the beneficiary or their circumstances."""
    project = WelfareProject.objects.select_for_update().select_related("organization").get(pk=project.pk)
    _open(project, today)
    if project.campaign_id:
        raise ApiException("already_due", "This project is already a due.", 409)
    if due_on < today:
        raise ApiException("due_in_past", "The due date can't be in the past.", 400)
    if project.deadline and due_on > project.deadline:
        raise ApiException("due_after_deadline", "The due date falls after the project closes.", 400)
    selected = project.audience == WelfareProject.Audience.SELECTED
    campaign = Campaign.objects.create(
        organization=project.organization,
        title=DUE_TITLE,
        amount_minor=amount_minor,
        currency=project.currency,
        cadence=Campaign.Cadence.ONCE,
        starts_on=due_on,
        ends_on=due_on,
        audience=Campaign.Audience.SELECTED if selected else Campaign.Audience.ALL,
        created_by=actor,
    )
    if selected:
        CampaignMember.objects.bulk_create(
            CampaignMember(campaign=campaign, member_id=member_id)
            for member_id in project.audience_members.exclude(pk=project.beneficiary_id).values_list(
                "pk", flat=True
            )
        )
    elif project.beneficiary_id:
        CampaignMember.objects.create(
            campaign=campaign,
            member_id=project.beneficiary_id,
            waived=True,
            waive_reason="The project's beneficiary",
        )
    project.campaign = campaign
    project.save(update_fields=["campaign"])
    dues.generate(campaign, today)
    return project


@transaction.atomic
def close(project: WelfareProject) -> WelfareProject:
    """Close by hand: the ledger stays, read-only, and a required project's campaign makes no more dues.
    Dues already made stay owed until paid or waived."""
    project = WelfareProject.objects.select_for_update().get(pk=project.pk)
    now = timezone.now()
    if not project.closed_at:
        project.closed_at = now
        project.save(update_fields=["closed_at"])
    if project.campaign_id:
        Campaign.objects.filter(pk=project.campaign_id, closed_at__isnull=True).update(closed_at=now)
    return project


def visits(project: WelfareProject, user) -> list[dict]:
    """The planned visits and support activities linked to the project that the viewer may see, with
    who is going (display names, as the activity's audience sees them)."""
    from activities import service as activities
    from activities.models import Activity, Rsvp

    shown = activities.visible(user, project.organization).filter(welfare_project=project)
    if not activities.is_staff(user, project.organization):
        shown = shown.exclude(status=Activity.Status.DRAFT)
    rows = []
    for activity in shown.prefetch_related("rsvps__user").order_by("starts_at", "id"):
        going = sorted(
            r.user.display_name
            for r in activity.rsvps.all()
            if r.answer == Rsvp.Answer.GOING and not r.waitlisted
        )
        rows.append(
            {
                "id": activity.id,
                "title": activity.title,
                "starts_at": activity.starts_at,
                "ends_at": activity.ends_at,
                "place": activity.place,
                "status": activity.status,
                "going": going,
            }
        )
    return rows


@transaction.atomic
def hide(project: WelfareProject) -> WelfareProject:
    project = WelfareProject.objects.select_for_update().get(pk=project.pk)
    if not project.hidden_at:
        project.hidden_at = timezone.now()
        project.save(update_fields=["hidden_at"])
    return project
