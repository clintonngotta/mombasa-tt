"""Door visits, passes and takings at facility branches (REQ-044, TASK-102).

Staff record who came, the pass sold, what they collected and how. The amount is the pass's price as the
facility set it: it is never typed in, so it is never invented. Recording collection is not payment
processing. A visit is never changed: a mistake is reversed with a reason, and the original stays.
"""

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from core.exceptions import ApiException

from .models import Pass, Venue, Visit
from .profile import local_now


def today_at(venue: Venue) -> date:
    return local_now(venue).date()


def active_pass(player, venue: Venue, on: date) -> Visit | None:
    """The player's pass at this branch that covers `on`: a longer pass or a bundle bought earlier, not
    reversed, still valid, and (for a bundle) with sessions left. Day passes cover only their day."""
    sales = (
        Visit.objects.filter(
            player=player,
            venue=venue,
            covered_by__isnull=True,
            reversed_at__isnull=True,
            visited_on__lte=on,
            valid_until__gte=on,
        )
        .select_related("pass_sold")
        .annotate(used=Count("uses", filter=Q(uses__reversed_at__isnull=True)))
        .order_by("valid_until")
    )
    for sale in sales:
        bundle = sale.pass_sold.kind == Pass.Kind.SESSIONS
        if not bundle or sale.used + 1 < sale.pass_sold.sessions:
            return sale
    return None


@transaction.atomic
def record(venue: Venue, actor, *, pass_sold=None, player=None, walk_in_name="", method, reference=""):
    """Record one visit at the door. With method `pass` the player's active pass covers it."""
    on = today_at(venue)
    if method == Visit.Method.PASS:
        if player is None:
            raise ApiException("pass_needs_player", "Only a Coast TT player can visit on a pass.", 400)
        # Lock the player's row so two door screens can't both use a bundle's last session.
        type(player).objects.select_for_update().filter(pk=player.pk).first()
        sale = active_pass(player, venue, on)
        if sale is None:
            raise ApiException("no_active_pass", "This player has no pass that covers today here.", 409)
        if Visit.objects.filter(covered_by=sale, visited_on=on, reversed_at__isnull=True).exists() or (
            sale.visited_on == on
        ):
            raise ApiException("already_in_today", "This pass was already used here today.", 409)
        return Visit.objects.create(
            venue=venue,
            pass_sold=sale.pass_sold,
            player=player,
            covered_by=sale,
            amount_minor=0,
            currency=sale.currency,
            method=method,
            visited_on=on,
            valid_until=on,
            recorded_by=actor,
        )
    if pass_sold is None or pass_sold.venue_id != venue.pk or not pass_sold.active:
        raise ApiException("pass_unavailable", "Choose one of this branch's prices in use.", 400)
    if method != Visit.Method.CASH and not reference.strip():
        raise ApiException("reference_required", "Enter the M-Pesa or payment reference.", 400)
    return Visit.objects.create(
        venue=venue,
        pass_sold=pass_sold,
        player=player,
        walk_in_name="" if player else walk_in_name.strip(),
        amount_minor=pass_sold.amount_minor,
        currency=pass_sold.currency,
        method=method,
        reference=reference.strip(),
        visited_on=on,
        valid_until=on + timedelta(days=pass_sold.days - 1),
        recorded_by=actor,
    )


@transaction.atomic
def reverse(visit: Visit, actor, reason: str) -> Visit:
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.reversed_at is not None:
        raise ApiException("already_reversed", "This visit was already reversed.", 409)
    if visit.uses.filter(reversed_at__isnull=True).exists():
        raise ApiException("pass_in_use", "Visits were made on this pass. Reverse those first.", 409)
    visit.reversed_at = timezone.now()
    visit.reversed_by = actor
    visit.reversal_reason = reason
    visit.save(update_fields=["reversed_at", "reversed_by", "reversal_reason"])
    return visit


def takings(visits) -> dict:
    """Totals of what was collected, leaving out reversed visits: per day, branch, method and pass, and
    overall, each per currency. Visits on a pass collect nothing and count only as visits."""
    kept = visits.filter(reversed_at__isnull=True)

    def grouped(*fields):
        rows = (
            kept.values(*fields, "currency")
            .annotate(amount_minor=Sum("amount_minor"), visits=Count("id"))
            .order_by(*fields, "currency")
        )
        return list(rows)

    return {
        "total": grouped(),
        "by_day": [{**row, "day": row.pop("visited_on")} for row in grouped("visited_on")],
        "by_branch": [
            {**row, "venue_id": row.pop("venue"), "venue_name": row.pop("venue__name")}
            for row in grouped("venue", "venue__name")
        ],
        "by_method": grouped("method"),
        "by_pass": [
            {**row, "pass_id": row.pop("pass_sold"), "pass_name": row.pop("pass_sold__name")}
            for row in grouped("pass_sold", "pass_sold__name")
        ],
        "reversed": visits.filter(reversed_at__isnull=False).count(),
    }
