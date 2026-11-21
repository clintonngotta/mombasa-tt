"""The manual ledger (REQ-022, TASK-037). Finance staff record and match; members see their own."""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from attachments.images import MAX_UPLOAD_BYTES, OUTPUT_CONTENT_TYPE, normalize_image
from attachments.models import Attachment
from core.exceptions import ApiException
from organizations.access import require_membership, require_permission
from organizations.committee import local_today
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import dues, ledger, summaries, welfare
from .models import Campaign, CampaignMember, Charge, Expense, WelfareContribution, WelfareProject
from .serializers import (
    AllocateSerializer,
    BalanceSerializer,
    CampaignDuesSerializer,
    CampaignSerializer,
    CampaignTermSerializer,
    CampaignUpdateSerializer,
    ChargeSerializer,
    ExpenseSerializer,
    FinanceReasonSerializer,
    MyFinancesSerializer,
    PaymentSerializer,
    PurposesSerializer,
    PurposeTotalSerializer,
    ReceiptUploadSerializer,
    RemindedSerializer,
    WelfareContributionSerializer,
    WelfareDueSerializer,
    WelfareProjectSerializer,
    WelfareUpdateSerializer,
)

RECEIPT_SIDE = 1600  # long enough to read a till slip
VIEW = (Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE)
MANAGE = Permission.FINANCES_MANAGE


def _org(pk) -> Organization:
    return get_object_or_404(Organization, pk=pk)


def _member(organization, user_id):
    """Someone who is, or was, a member: the ledger keeps what former members owe."""
    if user_id is None or not Membership.objects.filter(organization=organization, user_id=user_id).exists():
        raise ApiException("not_a_member", "Choose a member of the organization.", 400)
    return get_object_or_404(get_user_model(), pk=user_id)


def charges_of(organization):
    return organization.charges.select_related("member").prefetch_related("allocations__payment")


def payments_of(organization):
    return organization.payments.select_related("payer").prefetch_related("allocations")


def balances(charges, payments) -> list[dict]:
    rows = defaultdict(lambda: {"owed_minor": 0, "credit_minor": 0})
    names = {}
    for charge in charges.filter(member__isnull=False):  # a walk-in settles at the door
        key = (charge.member_id, charge.currency)
        rows[key]["owed_minor"] += ledger.outstanding(charge)
        names[charge.member_id] = charge.member.display_name
    for payment in payments.filter(payer__isnull=False):
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


def _expenses(organization):
    return organization.expenses.select_related("campaign")


class ExpensesView(APIView):
    """Spending (REQ-024): finance staff read it with receipts; finance managers record it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("campaign", str, description="Only this campaign's")],
        responses={200: ExpenseSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, *VIEW)
        found = _expenses(organization)
        if campaign := request.query_params.get("campaign"):
            found = found.filter(campaign_id=campaign)
        return Response(ExpenseSerializer(found, many=True).data)

    @extend_schema(request=ExpenseSerializer, responses={201: ExpenseSerializer})
    def post(self, request, organization_pk):
        """Record money spent. It may exceed what was received: the purpose then shows a deficit."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        body = ExpenseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        campaign = summaries.check_campaign(organization, data.pop("campaign_id"))
        if campaign and campaign.currency != data["currency"]:
            raise ApiException("currency_mismatch", "The campaign is kept in another currency.", 400)
        expense = Expense.objects.create(
            organization=organization, campaign=campaign, recorded_by=request.user, **data
        )
        return Response(ExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)


class ReverseExpenseView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=FinanceReasonSerializer, responses={200: ExpenseSerializer})
    def post(self, request, organization_pk, pk):
        """Reverse an expense recorded in error; it stays, with who reversed it and why."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        expense = get_object_or_404(_expenses(organization), pk=pk)
        body = FinanceReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        expense = summaries.reverse_expense(expense, request.user, body.validated_data["reason"])
        return Response(ExpenseSerializer(expense).data)


class ExpenseReceiptView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_scope = "uploads"

    @extend_schema(
        request={"multipart/form-data": ReceiptUploadSerializer}, responses={200: ExpenseSerializer}
    )
    def put(self, request, organization_pk, pk):
        """Attach (or replace) the receipt photo. Stored privately, re-encoded without metadata."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, MANAGE)
        expense = get_object_or_404(_expenses(organization), pk=pk)
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_UPLOAD_BYTES + 64 * 1024:
            raise ValidationError({"file": "Choose an image under 5 MB."})
        body = ReceiptUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        content = normalize_image(body.validated_data["file"], max_side=RECEIPT_SIDE)
        new = None
        try:
            with transaction.atomic():
                expense = Expense.objects.select_for_update().get(pk=expense.pk)
                old = expense.receipt
                new = Attachment.store(
                    owner=request.user,
                    purpose=Attachment.Purpose.RECEIPT,
                    content=content,
                    content_type=OUTPUT_CONTENT_TYPE,
                )
                expense.receipt = new
                expense.save(update_fields=["receipt"])
                if old:
                    old.delete()
        except BaseException:
            if new is not None:
                new.discard_file()
            raise
        return Response(ExpenseSerializer(get_object_or_404(_expenses(organization), pk=pk)).data)


class SummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PurposeTotalSerializer(many=True)})
    def get(self, request, organization_pk):
        """Per purpose: received, spent and remaining (negative is a deficit), and dues still expected.
        Member balances are under balances/."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, *VIEW)
        dues.catch_up(organization)
        return Response(PurposeTotalSerializer(summaries.purpose_totals(organization), many=True).data)


class PurposesView(APIView):
    """What members' contributions paid for: each campaign's totals and its spending, without receipts
    or anyone's own payments. Members only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PurposesSerializer})
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        require_membership(request.user, organization)
        spending = organization.expenses.filter(summaries.STANDING_EXPENSE, campaign__isnull=False)
        data = {
            "purposes": summaries.purpose_totals(organization, campaigns_only=True),
            "spending": [
                {
                    "campaign_id": e.campaign_id,
                    "description": e.description,
                    "amount_minor": e.amount_minor,
                    "currency": e.currency,
                    "spent_on": e.spent_on,
                }
                for e in spending
            ],
        }
        return Response(PurposesSerializer(data).data)


def _welfare_context(request, organization):
    return {
        "today": local_today(organization),
        "user": request.user,
        "staff": welfare.is_staff(request.user, organization),
    }


def _welfare_out(request, project, organization, status_code=status.HTTP_200_OK):
    context = _welfare_context(request, organization)
    return Response(WelfareProjectSerializer(project, context=context).data, status=status_code)


def _welfare_projects(organization):
    return organization.welfare_projects.select_related("beneficiary", "organization", "campaign")


def _visible_project(request, organization_pk, pk):
    """The project for staff, or for a member of its audience while it isn't hidden; 404 otherwise."""
    organization = _org(organization_pk)
    project = get_object_or_404(_welfare_projects(organization), pk=pk)
    if welfare.is_staff(request.user, organization):
        return organization, project, True
    require_membership(request.user, organization)
    if not welfare.visible_to_member(project, request.user):
        raise Http404
    return organization, project, False


class WelfareProjectsView(APIView):
    """Welfare projects (REQ-038). Members see those meant for them; welfare and finance staff see all."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: WelfareProjectSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = _org(organization_pk)
        projects = list(_welfare_projects(organization))
        if not welfare.is_staff(request.user, organization):
            require_membership(request.user, organization)
            projects = [p for p in projects if welfare.visible_to_member(p, request.user)]
        context = _welfare_context(request, organization)
        return Response(WelfareProjectSerializer(projects, many=True, context=context).data)

    @extend_schema(request=WelfareProjectSerializer, responses={201: WelfareProjectSerializer})
    @transaction.atomic
    def post(self, request, organization_pk):
        """Set up a project. Its audience hears that it opened, never what it is about."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, Permission.WELFARE_MANAGE)
        body = WelfareProjectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        member_ids = data.pop("member_ids")
        beneficiary_id = data.pop("beneficiary_id")
        beneficiary = _member(organization, beneficiary_id) if beneficiary_id else None
        if data.get("audience") == WelfareProject.Audience.SELECTED and not member_ids:
            raise ApiException("members_required", "Choose the members this project is for.", 400)
        project = WelfareProject.objects.create(
            organization=organization, beneficiary=beneficiary, created_by=request.user, **data
        )
        if project.audience == WelfareProject.Audience.SELECTED:
            project.audience_members.set([_member(organization, user_id) for user_id in member_ids])
        from notifications import triggers

        triggers.welfare_opened(project)
        return _welfare_out(request, project, organization, status.HTTP_201_CREATED)


class WelfareProjectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: WelfareProjectSerializer})
    def get(self, request, organization_pk, pk):
        organization, project, _ = _visible_project(request, organization_pk, pk)
        return _welfare_out(request, project, organization)

    @extend_schema(request=WelfareUpdateSerializer, responses={200: WelfareProjectSerializer})
    def patch(self, request, organization_pk, pk):
        organization = _org(organization_pk)
        require_permission(request.user, organization, Permission.WELFARE_MANAGE)
        project = get_object_or_404(_welfare_projects(organization), pk=pk)
        if welfare.is_closed(project, local_today(organization)):
            raise ApiException("project_closed", "This project is closed.", 409)
        body = WelfareUpdateSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        for field, value in body.validated_data.items():
            setattr(project, field, value)
        project.save()
        return _welfare_out(request, project, organization)


class HideWelfareView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: WelfareProjectSerializer})
    def post(self, request, organization_pk, pk):
        """Hide the project from members: the beneficiary may ask for it themselves. Staff still see
        it, and its ledger stays."""
        organization = _org(organization_pk)
        project = get_object_or_404(_welfare_projects(organization), pk=pk)
        if project.beneficiary_id != request.user.pk:
            require_permission(request.user, organization, Permission.WELFARE_MANAGE)
        project = welfare.hide(project)
        if not welfare.is_staff(request.user, organization):
            return Response(status=status.HTTP_204_NO_CONTENT)
        return _welfare_out(request, project, organization)


class CloseWelfareView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: WelfareProjectSerializer})
    def post(self, request, organization_pk, pk):
        """Close the project: its totals and records stay, read-only."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, Permission.WELFARE_MANAGE)
        project = welfare.close(get_object_or_404(_welfare_projects(organization), pk=pk))
        return _welfare_out(request, _welfare_projects(organization).get(pk=project.pk), organization)


class WelfareDueView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=WelfareDueSerializer, responses={200: WelfareProjectSerializer})
    def post(self, request, organization_pk, pk):
        """Make giving required: a one-time due for the project's audience, the beneficiary excepted.
        Needs both welfare.manage and finances.manage, since it makes members owe. It can't be undone
        here; finance staff waive dues or close the campaign as for any other."""
        organization = _org(organization_pk)
        require_permission(request.user, organization, Permission.WELFARE_MANAGE)
        require_permission(request.user, organization, MANAGE)
        project = get_object_or_404(_welfare_projects(organization), pk=pk)
        body = WelfareDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        today = local_today(organization)
        amount = body.validated_data.get("amount_minor") or project.suggested_minor
        if amount is None:
            raise ApiException("amount_required", "Set how much each member owes.", 400)
        due_on = body.validated_data.get("due_on") or project.deadline or today
        welfare.make_due(project, request.user, today, amount_minor=amount, due_on=due_on)
        return _welfare_out(request, _welfare_projects(organization).get(pk=project.pk), organization)


def _welfare_staff(request, organization_pk, pk, record=False):
    organization = _org(organization_pk)
    allowed = welfare.can_record if record else welfare.is_staff
    if not allowed(request.user, organization):
        require_permission(request.user, organization, Permission.WELFARE_MANAGE)
    return organization, get_object_or_404(_welfare_projects(organization), pk=pk)


class WelfareContributionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: WelfareContributionSerializer(many=True)})
    def get(self, request, organization_pk, pk):
        """Every gift with its giver, anonymous ones included: welfare and finance staff only."""
        _, project = _welfare_staff(request, organization_pk, pk)
        found = project.contributions.select_related("contributor", "payment")
        return Response(WelfareContributionSerializer(found, many=True).data)

    @extend_schema(
        request=WelfareContributionSerializer,
        responses={201: WelfareContributionSerializer, 200: WelfareContributionSerializer},
    )
    def post(self, request, organization_pk, pk):
        """Record a gift received outside Coast TT. Sending the same request_key again records nothing."""
        organization, project = _welfare_staff(request, organization_pk, pk, record=True)
        body = WelfareContributionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        contributor = _member(organization, data.pop("contributor_id"))
        before = WelfareContribution.objects.filter(project=project).count()
        made = welfare.contribute(
            project,
            request.user,
            local_today(organization),
            contributor=contributor,
            anonymous=data.pop("anonymous"),
            request_key=data.pop("request_key"),
            **data,
        )
        new = WelfareContribution.objects.filter(project=project).count() > before
        return Response(
            WelfareContributionSerializer(made).data,
            status=status.HTTP_201_CREATED if new else status.HTTP_200_OK,
        )


class ReverseWelfareContributionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=FinanceReasonSerializer, responses={200: WelfareContributionSerializer})
    def post(self, request, organization_pk, pk, contribution_pk):
        organization, project = _welfare_staff(request, organization_pk, pk, record=True)
        contribution = get_object_or_404(project.contributions, pk=contribution_pk)
        body = FinanceReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        welfare.reverse_contribution(
            contribution, request.user, body.validated_data["reason"], local_today(organization)
        )
        contribution = WelfareContribution.objects.select_related("contributor", "payment").get(
            pk=contribution.pk
        )
        return Response(WelfareContributionSerializer(contribution).data)


class WelfareExpensesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ExpenseSerializer(many=True)})
    def get(self, request, organization_pk, pk):
        _, project = _welfare_staff(request, organization_pk, pk)
        return Response(ExpenseSerializer(project.expenses.all(), many=True).data)

    @extend_schema(request=ExpenseSerializer, responses={201: ExpenseSerializer})
    def post(self, request, organization_pk, pk):
        """Record spending, a visit gift say. It may exceed what was given: the deficit shows."""
        organization, project = _welfare_staff(request, organization_pk, pk, record=True)
        body = ExpenseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        data.pop("campaign_id", None)
        expense = welfare.spend(project, request.user, local_today(organization), **data)
        return Response(ExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)
