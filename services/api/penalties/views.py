"""Club penalties for absences (REQ-054).

Governance staff set the rules, ask the app to propose penalties, and issue or waive each with a reason,
under /organizations/{id}/. A rule with a fine also takes the finance permission, since it makes members
owe. A member reads their own issued and waived penalties under /me/absence-penalties/ and appeals once.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.access import effective_permissions, require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import service
from .models import AbsencePenalty, AbsenceRule
from .serializers import (
    AbsencePenaltySerializer,
    AbsenceRuleSerializer,
    AbsenceRulesSerializer,
    AppealDecisionSerializer,
    AppealSerializer,
    IssueSerializer,
    MyAbsencePenaltySerializer,
    ProposedSerializer,
    WaiveSerializer,
)

GOVERNANCE = Permission.GOVERNANCE_MANAGE
MAX_PENALTIES = 200
SHOWN_TO_MEMBER = (AbsencePenalty.Status.ISSUED, AbsencePenalty.Status.WAIVED)


def staff_organization(request, organization_pk) -> Organization:
    organization = get_object_or_404(Organization, pk=organization_pk)
    require_permission(request.user, organization, GOVERNANCE)
    return organization


class AbsenceRulesView(APIView):
    """GET/PUT /organizations/{org}/absence-rules/: what each kind of absence costs. Governance staff;
    a rule with a fine also takes finances.manage."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AbsenceRuleSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        return Response(AbsenceRuleSerializer(organization.absence_rules.all(), many=True).data)

    @extend_schema(request=AbsenceRulesSerializer, responses={200: AbsenceRuleSerializer(many=True)})
    def put(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        body = AbsenceRulesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        rules = body.validated_data["rules"]
        fines = any(rule.get("fine_minor") for rule in rules)
        if fines and Permission.FINANCES_MANAGE not in effective_permissions(request.user, organization):
            raise ApiException("permission_denied", "A rule with a fine takes finances.manage too.", 403)
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            kept = []
            for rule in rules:
                made, _ = AbsenceRule.objects.update_or_create(
                    organization=organization,
                    applies_to=rule["applies_to"],
                    defaults={
                        "kind": rule.get("kind", "warning"),
                        "suspension_events": rule.get("suspension_events"),
                        "points": rule.get("points"),
                        "fine_minor": rule.get("fine_minor"),
                        "apology_excuses": rule.get("apology_excuses", True),
                        "active": rule.get("active", True),
                        "updated_by": request.user,
                    },
                )
                kept.append(made.pk)
            organization.absence_rules.exclude(pk__in=kept).delete()
        return Response(AbsenceRuleSerializer(organization.absence_rules.all(), many=True).data)


class AbsencePenaltiesView(APIView):
    """GET /organizations/{org}/absence-penalties/: proposed penalties first, then the latest decided;
    `?status=` narrows it. For governance staff."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=["proposed", "issued", "waived"])],
        responses={200: AbsencePenaltySerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        found = organization.absence_penalties.select_related("member", "decided_by")
        wanted = request.query_params.get("status")
        if wanted in AbsencePenalty.Status.values:
            found = found.filter(status=wanted)
        found = sorted(
            found[:MAX_PENALTIES], key=lambda p: (p.status != "proposed", -p.happened_on.toordinal())
        )
        return Response(AbsencePenaltySerializer(found, many=True).data)


class ProposeView(APIView):
    """POST /organizations/{org}/absence-penalties/propose/: look for absences of the last 90 days that
    a rule covers and propose a penalty for each that has none. Nothing is issued by this."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: ProposedSerializer})
    def post(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        return Response({"proposed": service.propose(organization)})


class PenaltyAction(APIView):
    permission_classes = [IsAuthenticated]

    def penalty(self, request, organization_pk, pk) -> AbsencePenalty:
        organization = staff_organization(request, organization_pk)
        return get_object_or_404(AbsencePenalty, organization=organization, pk=pk)

    def shown(self, penalty) -> Response:
        fresh = AbsencePenalty.objects.select_related("member", "decided_by").get(pk=penalty.pk)
        return Response(AbsencePenaltySerializer(fresh).data)


class IssueView(PenaltyAction):
    """POST .../absence-penalties/{id}/issue/: the penalty stands. The member is told, and a fine becomes
    a charge they owe."""

    @extend_schema(request=IssueSerializer, responses={200: AbsencePenaltySerializer})
    def post(self, request, organization_pk, pk):
        body = IssueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        penalty = self.penalty(request, organization_pk, pk)
        return self.shown(service.issue(penalty, request.user, body.validated_data["reason"]))


class WaiveView(PenaltyAction):
    """POST .../absence-penalties/{id}/waive/: drop a proposed or issued penalty, with a reason. A fine
    already charged is waived with it."""

    @extend_schema(request=WaiveSerializer, responses={200: AbsencePenaltySerializer})
    def post(self, request, organization_pk, pk):
        body = WaiveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        penalty = self.penalty(request, organization_pk, pk)
        return self.shown(service.waive(penalty, request.user, body.validated_data["reason"]))


class AppealDecisionView(PenaltyAction):
    """POST .../absence-penalties/{id}/appeal/: decide the member's appeal. Upholding it waives the
    penalty."""

    @extend_schema(request=AppealDecisionSerializer, responses={200: AbsencePenaltySerializer})
    def post(self, request, organization_pk, pk):
        body = AppealDecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        penalty = self.penalty(request, organization_pk, pk)
        return self.shown(service.decide_appeal(penalty, request.user, **body.validated_data))


def mine(user):
    return AbsencePenalty.objects.filter(member=user, status__in=SHOWN_TO_MEMBER).select_related(
        "organization"
    )


class MyAbsencePenaltiesView(APIView):
    """GET /me/absence-penalties/: penalties issued to you, and those waived, in every club. A penalty
    that is only proposed isn't shown: nothing has been decided."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MyAbsencePenaltySerializer(many=True)})
    def get(self, request):
        return Response(MyAbsencePenaltySerializer(mine(request.user)[:MAX_PENALTIES], many=True).data)


class MyAppealView(APIView):
    """POST /me/absence-penalties/{id}/appeal/: say why an issued penalty is wrong. Once per penalty."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=AppealSerializer, responses={200: MyAbsencePenaltySerializer})
    def post(self, request, pk):
        body = AppealSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        penalty = get_object_or_404(mine(request.user), pk=pk)
        service.appeal(penalty, body.validated_data["text"])
        return Response(MyAbsencePenaltySerializer(mine(request.user).get(pk=pk)).data)
