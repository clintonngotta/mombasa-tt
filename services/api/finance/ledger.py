"""Ledger rules (REQ-022, TASK-037): recording, matching and reversing, and the balances that follow."""

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from core.exceptions import ApiException

from .models import Allocation, Charge, Payment

STANDING = Q(payment__reversed_at__isnull=True)


def paid_towards(charge: Charge) -> int:
    return charge.allocations.filter(STANDING).aggregate(total=Sum("amount_minor"))["total"] or 0


def outstanding(charge: Charge) -> int:
    """What is still owed on the charge: nothing once waived."""
    if charge.waived_at:
        return 0
    return charge.amount_minor - paid_towards(charge)


def allocated_from(payment: Payment) -> int:
    return payment.allocations.aggregate(total=Sum("amount_minor"))["total"] or 0


def credit(payment: Payment) -> int:
    """What of the payment isn't matched to anything yet: kept visible, never spent silently."""
    if payment.reversed_at:
        return 0
    return payment.amount_minor - allocated_from(payment)


@transaction.atomic
def record(
    organization,
    actor,
    *,
    payer,
    amount_minor,
    currency,
    method,
    reference,
    received_on,
    request_key,
    walk_in_name="",
):
    """Record money received. The same request sent twice records it once and returns the first."""
    existing = Payment.objects.filter(organization=organization, request_key=request_key).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                organization=organization,
                payer=payer,
                amount_minor=amount_minor,
                currency=currency,
                method=method,
                reference=reference,
                received_on=received_on,
                request_key=request_key,
                walk_in_name=walk_in_name,
                recorded_by=actor,
            )
    except IntegrityError:
        return Payment.objects.get(organization=organization, request_key=request_key), False
    return payment, True


@transaction.atomic
def allocate(payment: Payment, charge: Charge, amount_minor: int, actor) -> Allocation:
    """Match part of a payment to a charge: same organization and currency, never more than the payment
    has left or the charge still owes."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    charge = Charge.objects.select_for_update().get(pk=charge.pk)
    if payment.reversed_at:
        raise ApiException("payment_reversed", "This payment was reversed.", 409)
    if charge.organization_id != payment.organization_id:
        raise ApiException("other_organization", "That charge belongs to another organization.", 400)
    if charge.currency != payment.currency:
        raise ApiException(
            "currency_mismatch", "The payment and the charge are in different currencies.", 400
        )
    if charge.waived_at:
        raise ApiException("charge_waived", "This charge was waived.", 409)
    if amount_minor > credit(payment):
        raise ApiException("over_allocated", "More than this payment has left to match.", 400)
    if amount_minor > outstanding(charge):
        raise ApiException("over_allocated", "More than this charge still owes.", 400)
    return Allocation.objects.create(
        payment=payment, charge=charge, amount_minor=amount_minor, created_by=actor
    )


@transaction.atomic
def reverse(payment: Payment, actor, reason: str) -> Payment:
    """Mark a payment recorded in error. It stays, with who reversed it and why; what it paid off is
    owed again."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.reversed_at:
        raise ApiException("already_reversed", "This payment was already reversed.", 409)
    payment.reversed_at = timezone.now()
    payment.reversed_by = actor
    payment.reversal_reason = reason
    payment.save(update_fields=["reversed_at", "reversed_by", "reversal_reason"])
    return payment


@transaction.atomic
def waive(charge: Charge, actor, reason: str) -> Charge:
    charge = Charge.objects.select_for_update().get(pk=charge.pk)
    if charge.waived_at:
        return charge
    charge.waived_at = timezone.now()
    charge.waived_by = actor
    charge.waive_reason = reason
    charge.save(update_fields=["waived_at", "waived_by", "waive_reason"])
    return charge


def status(charge: Charge, today) -> str:
    """paid, partial, pending, overdue (a partly paid charge past its date is overdue) or waived."""
    if charge.waived_at:
        return "waived"
    left = outstanding(charge)
    if left <= 0:
        return "paid"
    if charge.due_on and charge.due_on < today:
        return "overdue"
    return "partial" if left < charge.amount_minor else "pending"
