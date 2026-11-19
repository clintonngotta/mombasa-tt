"""Door visits in the ledger (REQ-044 with REQ-022, TASK-104).

A paid visit is a charge for the pass sold (its price, never typed in), the money collected at the door
as a payment, and that payment matched to the charge in full, all made in the visit's own transaction.
The visit's id keys both, so posting twice changes nothing. Reversing the visit reverses the payment and
waives the charge, so the ledger nets to nothing and both records stay. A visit on a pass already held
collected nothing and posts nothing.
"""

from django.db import transaction

from . import ledger
from .models import Allocation, Charge, Payment

METHODS = {"cash": Payment.Method.CASH, "mpesa": Payment.Method.MPESA, "other": Payment.Method.OTHER}


@transaction.atomic
def post_visit(visit) -> Charge | None:
    if visit.amount_minor == 0 or visit.method not in METHODS:
        return None
    organization = visit.venue.organization
    who = {"walk_in_name": visit.walk_in_name}
    charge, made = Charge.objects.get_or_create(
        kind=Charge.Kind.VISIT,
        source_id=visit.id,
        defaults={
            "organization": organization,
            "member": visit.player,
            "purpose": f"{visit.pass_sold.name} at {visit.venue.name}",
            "amount_minor": visit.amount_minor,
            "currency": visit.currency,
            "due_on": visit.visited_on,
            "created_by": visit.recorded_by,
            **who,
        },
    )
    payment, _ = ledger.record(
        organization,
        visit.recorded_by,
        payer=visit.player,
        amount_minor=visit.amount_minor,
        currency=visit.currency,
        method=METHODS[visit.method],
        reference=visit.reference,
        received_on=visit.visited_on,
        request_key=visit.id,
        **who,
    )
    if made and not Allocation.objects.filter(payment=payment, charge=charge).exists():
        ledger.allocate(payment, charge, visit.amount_minor, visit.recorded_by)
    return charge


@transaction.atomic
def reverse_visit(visit, actor, reason: str) -> None:
    charge = Charge.objects.filter(kind=Charge.Kind.VISIT, source_id=visit.id).first()
    if charge is None:
        return
    payment = Payment.objects.filter(organization_id=charge.organization_id, request_key=visit.id).first()
    if payment and not payment.reversed_at:
        ledger.reverse(payment, actor, f"Visit reversed: {reason}")
    ledger.waive(charge, actor, f"Visit reversed: {reason}")
