"""The manual ledger (REQ-022, TASK-037). Finance staff record and match; members see their own."""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.access import require_membership, require_permission
from organizations.committee import local_today
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import dues, ledger
from .models import Campaign, CampaignMember, Charge
from .serializers import (
    AllocateSerializer,
    BalanceSerializer,
    CampaignDuesSerializer,
    CampaignSerializer,
    CampaignTermSerializer,
    CampaignUpdateSerializer,
    ChargeSerializer,
    FinanceReasonSerializer,
    MyFinancesSerializer,
    PaymentSerializer,
    RemindedSerializer,
)

VIEW = (Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE)
MANAGE = Permission.FINANCES_MANAGE


def _org(pk) -> Organization:
    return get_object_or_404(Organization, pk=pk)


def _member(organization, user_id):
    """Someone who is, or was, a member: the ledger keeps what former members owe."""
    if not Membership.objects.filter(organization=organization, user_id=user_id).exists():
        raise ApiException("not_a_member", "Choose a member of the organization.", 400)
    return get_object_or_404(get_user_model(), pk=user_id)


def charges_of(organization):
    return organization.charges.select_related("member").prefetch_related("allocations__payment")


def payments_of(organization):
    return organization.payments.select_related("payer").prefetch_related("allocations")


def balances(charges, payments) -> list[dict]:
    rows = defaultdict(lambda: {"owed_minor": 0, "credit_minor": 0})
    names = {}
    for charge in charges:
        key = (charge.member_id, charge.currency)
        rows[key]["owed_minor"] += ledger.outstanding(charge)
        names[charge.member_id] = charge.member.display_name
    for payment in payments:
        key = (payment.payer_id, payment.currency)
        rows[key]["credit_minor"] += ledger.credit(payment)
        names[payment.payer_id] = payment.payer.display_name
    return [
        {"member_id": member, "member_name": names[member], "currency": currency, **totals}
        for (member, currency), totals in sorted(rows.items(), key=lambda kv: names[kv[0][0]].lower())
    ]


class ChargesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("member", str, description="Only this member's")],
        responses={200: ChargeSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, *VIEW)
        dues.catch_up(organization)
        found = charges_of(organization)
        if member := request.query_params.get("member"):
            found = found.filter(member_id=member)
        return Response(ChargeSerializer(found, many=True).data)

    @extend_schema(request=ChargeSerializer, responses={201: ChargeSerializer})
    def post(self, request, organization_pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        body = ChargeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        member = _member(organization, data.pop("member_id"))
        charge = Charge.objects.create(
            organization=organization, member=member, created_by=request.user, **data
        )
        return Response(ChargeSerializer(charge).data, status=status.HTTP_201_CREATED)


class WaiveChargeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=FinanceReasonSerializer, responses={200: ChargeSerializer})
    def post(self, request, organization_pk, pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        charge = get_object_or_404(organization.charges, pk=pk)
        body = FinanceReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            ChargeSerializer(ledger.waive(charge, request.user, body.validated_data["reason"])).data
        )


class PaymentsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PaymentSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, *VIEW)
        return Response(PaymentSerializer(payments_of(organization), many=True).data)

    @extend_schema(request=PaymentSerializer, responses={201: PaymentSerializer, 200: PaymentSerializer})
    def post(self, request, organization_pk):
        """Record money received. Repeating a request (same request_key) returns the first record."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        body = PaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        payer = _member(organization, data.pop("payer_id"))
        payment, made = ledger.record(organization, request.user, payer=payer, **data)
        code = status.HTTP_201_CREATED if made else status.HTTP_200_OK
        return Response(PaymentSerializer(payment).data, status=code)


class PaymentActionView(APIView):
    permission_classes = [IsAuthenticated]
    action = ""

    def post(self, request, organization_pk, pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        payment = get_object_or_404(organization.payments, pk=pk)
        if self.action == "allocate":
            body = AllocateSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            charge = get_object_or_404(organization.charges, pk=body.validated_data["charge_id"])
            ledger.allocate(payment, charge, body.validated_data["amount_minor"], request.user)
        else:
            body = FinanceReasonSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            ledger.reverse(payment, request.user, body.validated_data["reason"])
        payment.refresh_from_db()
        return Response(PaymentSerializer(payment).data)


class AllocateView(PaymentActionView):
    action = "allocate"

    @extend_schema(request=AllocateSerializer, responses={200: PaymentSerializer})
    def post(self, request, organization_pk, pk):
        """Match part of the payment to a charge."""
        return super().post(request, organization_pk, pk)


class ReversePaymentView(PaymentActionView):
    action = "reverse"

    @extend_schema(request=FinanceReasonSerializer, responses={200: PaymentSerializer})
    def post(self, request, organization_pk, pk):
        """Reverse a payment recorded in error; the original stays and what it paid is owed again."""
        return super().post(request, organization_pk, pk)


class BalancesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: BalanceSerializer(many=True)})
    def get(self, request, organization_pk):
        """Every member's outstanding balance and unmatched credit, per currency."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, *VIEW)
        dues.catch_up(organization)
        return Response(
            BalanceSerializer(balances(charges_of(organization), payments_of(organization)), many=True).data
        )


class MyFinancesView(APIView):
    """What the signed-in member owes and paid the organization. Nobody else's records."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MyFinancesSerializer})
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        require_membership(request.user, organization)
        dues.catch_up(organization)
        charges = charges_of(organization).filter(member=request.user)
        payments = payments_of(organization).filter(payer=request.user)
        today = local_today(organization)
        data = {
            "charges": charges,
            "payments": payments,
            "balances": balances(charges, payments),
            "dues": my_dues(charges, today),
        }
        return Response(MyFinancesSerializer(data, context={"today": today}).data)


def my_dues(charges, today) -> list[dict]:
    """Per campaign, what the member still owes on it and how much of that is overdue."""
    rows = {}
    for charge in charges.filter(campaign__isnull=False).select_related("campaign"):
        row = rows.setdefault(
            charge.campaign_id,
            {
                "campaign_id": charge.campaign_id,
                "title": charge.campaign.title,
                "cadence": charge.campaign.cadence,
                "currency": charge.currency,
                "outstanding_minor": 0,
                "overdue_minor": 0,
                "next_due_on": dues.next_period(charge.campaign, today),
            },
        )
        left = ledger.outstanding(charge)
        row["outstanding_minor"] += left
        if ledger.status(charge, today) == "overdue":
            row["overdue_minor"] += left
    return sorted(rows.values(), key=lambda r: r["title"].lower())


def _campaign_out(campaign, organization, status_code=status.HTTP_200_OK):
    context = {"today": local_today(organization)}
    return Response(CampaignSerializer(campaign, context=context).data, status=status_code)


def _campaigns(organization):
    return organization.campaigns.prefetch_related("terms__member")


class CampaignsView(APIView):
    """Contribution campaigns (REQ-023). Finance staff read them; finance managers set them up."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CampaignSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, *VIEW)
        dues.catch_up(organization)
        context = {"today": local_today(organization)}
        return Response(CampaignSerializer(_campaigns(organization), many=True, context=context).data)

    @extend_schema(request=CampaignSerializer, responses={201: CampaignSerializer})
    @transaction.atomic
    def post(self, request, organization_pk):
        """Set up a campaign. Its dues to date are generated at once; the rest as their dates come."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        body = CampaignSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        member_ids = data.pop("member_ids")
        data.setdefault("audience", Campaign.Audience.ALL)
        if data["audience"] == Campaign.Audience.SELECTED and not member_ids:
            raise ApiException("members_required", "Choose the members this campaign is for.", 400)
        campaign = Campaign.objects.create(organization=organization, created_by=request.user, **data)
        if data["audience"] == Campaign.Audience.SELECTED:
            for user_id in dict.fromkeys(member_ids):
                CampaignMember.objects.create(campaign=campaign, member=_member(organization, user_id))
        dues.generate(campaign, local_today(organization))
        return _campaign_out(campaign, organization, status.HTTP_201_CREATED)


class _CampaignAction(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, organization_pk, pk, *permissions):
        organization = _org(organization_pk)
        require_permission(request.user, organization, *permissions)
        return organization, get_object_or_404(_campaigns(organization), pk=pk)


class CampaignView(_CampaignAction):
    @extend_schema(responses={200: CampaignSerializer})
    def get(self, request, organization_pk, pk):
        organization, campaign = self._get(request, organization_pk, pk, *VIEW)
        return _campaign_out(campaign, organization)

    @extend_schema(request=CampaignUpdateSerializer, responses={200: CampaignSerializer})
    def patch(self, request, organization_pk, pk):
        """Change the title, description, amount or last date. Dues already generated keep theirs."""
        organization, campaign = self._get(request, organization_pk, pk, MANAGE)
        if campaign.closed_at:
            raise ApiException("campaign_closed", "This campaign is closed.", 409)
        body = CampaignUpdateSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        ends = body.validated_data.get("ends_on", campaign.ends_on)
        if ends and ends < campaign.starts_on:
            raise ApiException("bad_dates", "The last date can't be before the first.", 400)
        for field, value in body.validated_data.items():
            setattr(campaign, field, value)
        campaign.save()
        return _campaign_out(campaign, organization)


class CloseCampaignView(_CampaignAction):
    @extend_schema(request=None, responses={200: CampaignSerializer})
    def post(self, request, organization_pk, pk):
        """Stop generating dues. Dues already generated stay owed."""
        organization, campaign = self._get(request, organization_pk, pk, MANAGE)
        if not campaign.closed_at:
            dues.generate(campaign, local_today(organization))
            campaign.closed_at = timezone.now()
            campaign.save(update_fields=["closed_at"])
        return _campaign_out(campaign, organization)


class CampaignTermView(_CampaignAction):
    @extend_schema(request=CampaignTermSerializer, responses={200: CampaignSerializer})
    def post(self, request, organization_pk, pk):
        """Set one member's terms: included, their own amount, or waived with a reason. Periods already
        generated keep their dues; waive one of those on the charge itself."""
        organization, campaign = self._get(request, organization_pk, pk, MANAGE)
        body = CampaignTermSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        member = _member(organization, data.pop("member_id"))
        # Bring dues up to date first, so the change applies from the next period only.
        dues.generate(campaign, local_today(organization))
        CampaignMember.objects.update_or_create(campaign=campaign, member=member, defaults=data)
        return _campaign_out(get_object_or_404(_campaigns(organization), pk=pk), organization)


class CampaignDuesView(_CampaignAction):
    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=["pending", "partial", "paid", "overdue", "waived"],
                description="Only these",
            )
        ],
        responses={200: CampaignDuesSerializer},
    )
    def get(self, request, organization_pk, pk):
        """Every due the campaign made, with each one's status, and the totals still owed."""
        organization, campaign = self._get(request, organization_pk, pk, *VIEW)
        today = local_today(organization)
        dues.generate(campaign, today)
        rows = [
            (charge, ledger.status(charge, today), ledger.outstanding(charge))
            for charge in campaign.dues.select_related("member")
            .prefetch_related("allocations__payment")
            .order_by("-period", "member__display_name")
        ]
        counts = {}
        for _, state, _ in rows:
            counts[state] = counts.get(state, 0) + 1
        wanted = request.query_params.get("status")
        shown = [charge for charge, state, _ in rows if not wanted or state == wanted]
        data = {
            "counts": counts,
            "outstanding_minor": sum(left for _, _, left in rows),
            "overdue_minor": sum(left for _, state, left in rows if state == "overdue"),
            "dues": shown,
        }
        return Response(CampaignDuesSerializer(data, context={"today": today}).data)


class RemindCampaignView(_CampaignAction):
    @extend_schema(request=None, responses={200: RemindedSerializer})
    def post(self, request, organization_pk, pk):
        """Remind everyone overdue on the campaign. Pressing it again the same day sends nothing more."""
        organization, campaign = self._get(request, organization_pk, pk, MANAGE)
        return Response({"sent": dues.nudge(campaign, local_today(organization))})
