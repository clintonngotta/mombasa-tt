"""Welfare projects (REQ-038, TASK-074): voluntary giving to a shared cause, through the manual ledger.

A contribution is money received (a REQ-022 payment) matched in full to a paid welfare charge, so it
never leaves anyone owing: there is no overdue status for not giving. Spending is a REQ-024 expense on
the project. Received, spent and remaining reconcile the same way as any purpose, deficits included.
"""

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.models import Membership
from organizations.permissions import Permission

from . import ledger
from .models import Allocation, Charge, Expense, WelfareContribution, WelfareProject

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


def totals(project: WelfareProject) -> dict:
    received = (
        Allocation.objects.filter(
            charge__welfare__project=project, payment__reversed_at__isnull=True
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    spent = (
        project.expenses.filter(reversed_at__isnull=True).aggregate(total=Sum("amount_minor"))["total"] or 0
    )
    return {"received_minor": received, "spent_minor": spent, "remaining_minor": received - spent}


def own_total(project: WelfareProject, user) -> int:
    return (
        Allocation.objects.filter(
            charge__welfare__project=project,
            charge__welfare__contributor=user,
            payment__reversed_at__isnull=True,
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )


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


@transaction.atomic
def hide(project: WelfareProject) -> WelfareProject:
    project = WelfareProject.objects.select_for_update().get(pk=project.pk)
    if not project.hidden_at:
        project.hidden_at = timezone.now()
        project.save(update_fields=["hidden_at"])
    return project
