"""The manual ledger (REQ-022, TASK-037). Finance staff record and match; members see their own."""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.access import require_membership, require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import ledger
from .models import Charge
from .serializers import (
    AllocateSerializer,
    BalanceSerializer,
    ChargeSerializer,
    FinanceReasonSerializer,
    MyFinancesSerializer,
    PaymentSerializer,
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
        charges = charges_of(organization).filter(member=request.user)
        payments = payments_of(organization).filter(payer=request.user)
        data = {"charges": charges, "payments": payments, "balances": balances(charges, payments)}
        return Response(MyFinancesSerializer(data).data)
