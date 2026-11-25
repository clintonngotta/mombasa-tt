"""The financial year, and the annual report (REQ-041).

Finance staff set when the year ends, draft a report for a finished year, add a summary, publish it and
later amend it. A published report is read by the organization's members, and by anyone when it is made
public. It carries totals only: no member, payer, payee or receipt.
"""

from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.permissions import PublicReads
from organizations.access import effective_permissions, require_permission
from organizations.committee import local_today
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import reports
from .models import AnnualReport, FinanceSettings

VIEW = (Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE)
MANAGE = Permission.FINANCES_MANAGE
MAX_REPORTS = 60


class StrictFinanceFields(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", None) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class FinanceSettingsSerializer(StrictFinanceFields):
    year_end_month = serializers.IntegerField(min_value=1, max_value=12)
    year_end_day = serializers.IntegerField(min_value=1, max_value=31)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][attrs["year_end_month"] - 1]
        if attrs["year_end_day"] > days:
            raise serializers.ValidationError({"year_end_day": "That month has fewer days."})
        return attrs


class ReportLineSerializer(serializers.Serializer):
    label = serializers.CharField()
    amount_minor = serializers.IntegerField()


class ReportPurposeSerializer(serializers.Serializer):
    title = serializers.CharField()
    received_minor = serializers.IntegerField()
    spent_minor = serializers.IntegerField()
    net_minor = serializers.IntegerField(help_text="Received less spent; negative is a deficit.")


class ReportCurrencySerializer(serializers.Serializer):
    currency = serializers.CharField()
    opening_minor = serializers.IntegerField()
    receipts_minor = serializers.IntegerField()
    receipts = ReportLineSerializer(many=True)
    expenses_minor = serializers.IntegerField()
    expenses = ReportLineSerializer(many=True)
    purposes = ReportPurposeSerializer(many=True)
    closing_minor = serializers.IntegerField()
    outstanding_dues_minor = serializers.IntegerField()
    waived_minor = serializers.IntegerField()


class ReportFiguresSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    currencies = ReportCurrencySerializer(many=True)


class AnnualReportSerializer(serializers.Serializer):
    """A report: frozen figures once published, the ledger as it stands while a draft."""

    id = serializers.UUIDField()
    organization_name = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    version = serializers.IntegerField()
    amends = serializers.UUIDField(allow_null=True, help_text="The version this one corrects.")
    status = serializers.ChoiceField(choices=AnnualReport.Status.choices)
    narrative = serializers.CharField(allow_blank=True)
    public = serializers.BooleanField()
    changes = serializers.ListField(child=serializers.CharField())
    figures = ReportFiguresSerializer()
    published_at = serializers.DateTimeField(allow_null=True)
    published_by_name = serializers.CharField(allow_null=True)
    can_edit = serializers.BooleanField()


class NewReportSerializer(StrictFinanceFields):
    period_end = serializers.DateField(
        required=False, help_text="The year end to report on. Defaults to the latest year that has ended."
    )


class ReportUpdateSerializer(StrictFinanceFields):
    narrative = serializers.CharField(max_length=5000, trim_whitespace=True, allow_blank=True, required=False)
    public = serializers.BooleanField(required=False)


def shown(report: AnnualReport, user) -> dict:
    organization = report.organization
    staff = user.is_authenticated and MANAGE in effective_permissions(user, organization)
    draft = report.status == AnnualReport.Status.DRAFT
    figures = (
        reports.figures(organization, report.period_start, report.period_end) if draft else report.snapshot
    )
    return {
        "id": report.pk,
        "organization_name": organization.name,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "version": report.version,
        "amends": report.amends_id,
        "status": report.status,
        "narrative": report.narrative,
        "public": report.public,
        "changes": report.changes,
        "figures": figures,
        "published_at": report.published_at,
        "published_by_name": report.published_by.display_name if staff and report.published_by else None,
        "can_edit": bool(staff),
    }


def readable(user, organization: Organization):
    """The organization's reports the caller may read: finance staff all of them, members the published
    ones, anybody else (signed in or not) the published ones made public."""
    found = AnnualReport.objects.filter(organization=organization).select_related(
        "organization", "published_by"
    )
    if user.is_authenticated:
        if set(VIEW) & effective_permissions(user, organization):
            return found
        if Membership.objects.active().filter(organization=organization, user=user).exists():
            return found.filter(status=AnnualReport.Status.PUBLISHED)
    return found.filter(status=AnnualReport.Status.PUBLISHED, public=True)


class FinanceSettingsView(APIView):
    """GET/PUT /organizations/{org}/finance/settings/: the day the financial year ends."""

    @extend_schema(responses={200: FinanceSettingsSerializer})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, *VIEW)
        month, day = reports.year_end(organization)
        return Response({"year_end_month": month, "year_end_day": day})

    @extend_schema(request=FinanceSettingsSerializer, responses={200: FinanceSettingsSerializer})
    def put(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, MANAGE)
        body = FinanceSettingsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        FinanceSettings.objects.update_or_create(
            organization=organization, defaults={**body.validated_data, "updated_by": request.user}
        )
        return Response(body.validated_data)


class AnnualReportsView(APIView):
    """GET /organizations/{org}/annual-reports/: the reports you may read, latest first (public ones
    need no login). POST drafts the report of a finished year: finance managers."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={200: AnnualReportSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        found = readable(request.user, organization)[:MAX_REPORTS]
        return Response(
            AnnualReportSerializer([shown(report, request.user) for report in found], many=True).data
        )

    @extend_schema(request=NewReportSerializer, responses={201: AnnualReportSerializer})
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, MANAGE)
        body = NewReportSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        today = local_today(organization)
        try:
            start, end = (
                reports.period_for(organization, body.validated_data["period_end"])
                if "period_end" in body.validated_data
                else reports.period_ending(organization, today)
            )
        except ValueError as error:
            raise serializers.ValidationError({"period_end": "That isn't one of your year ends."}) from error
        if end >= today:
            raise ApiException("year_not_over", "Report on a year once it has ended.", 409)
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            if AnnualReport.objects.filter(organization=organization, period_end=end).exists():
                raise ApiException("report_exists", "That year has a report. Amend it instead.", 409)
            report = AnnualReport.objects.create(
                organization=organization, period_start=start, period_end=end, created_by=request.user
            )
        return Response(
            AnnualReportSerializer(shown(report, request.user)).data, status=status.HTTP_201_CREATED
        )


class ReportAction(APIView):
    def locked(self, request, organization_pk, pk) -> AnnualReport:
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, MANAGE)
        return get_object_or_404(
            AnnualReport.objects.select_for_update(of=("self",)).select_related(
                "organization", "published_by"
            ),
            organization=organization,
            pk=pk,
        )

    def reply(self, request, report, code=status.HTTP_200_OK) -> Response:
        return Response(AnnualReportSerializer(shown(report, request.user)).data, status=code)


class AnnualReportView(ReportAction):
    """GET /organizations/{org}/annual-reports/{id}/. PATCH sets the summary of a draft, or whether a
    report is public. DELETE discards a draft."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={200: AnnualReportSerializer})
    def get(self, request, organization_pk, pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        return self.reply(request, get_object_or_404(readable(request.user, organization), pk=pk))

    @extend_schema(request=ReportUpdateSerializer, responses={200: AnnualReportSerializer})
    def patch(self, request, organization_pk, pk):
        body = ReportUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            report = self.locked(request, organization_pk, pk)
            data = body.validated_data
            if "narrative" in data:
                if report.status != AnnualReport.Status.DRAFT:
                    raise ApiException("report_published", "A published report can't change. Amend it.", 409)
                report.narrative = data["narrative"]
            if "public" in data:
                report.public = data["public"]
            report.save(update_fields=["narrative", "public"])
        return self.reply(request, report)

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        with transaction.atomic():
            report = self.locked(request, organization_pk, pk)
            if report.status != AnnualReport.Status.DRAFT:
                raise ApiException("report_published", "A published report stays on record.", 409)
            report.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublishReportView(ReportAction):
    """POST .../annual-reports/{id}/publish/: freeze the figures as they stand. An amendment also
    records what differs from the version before."""

    @extend_schema(request=None, responses={200: AnnualReportSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            report = self.locked(request, organization_pk, pk)
            if report.status != AnnualReport.Status.DRAFT:
                raise ApiException("report_published", "This version is already published.", 409)
            report.snapshot = reports.figures(report.organization, report.period_start, report.period_end)
            if report.amends_id:
                report.changes = reports.differences(report.amends.snapshot, report.snapshot)
                report.public = report.amends.public
            report.status = AnnualReport.Status.PUBLISHED
            report.published_by, report.published_at = request.user, timezone.now()
            report.save()
        return self.reply(request, report)


class AmendReportView(ReportAction):
    """POST .../annual-reports/{id}/amend/: start a new version of the latest published report of that
    year. The published version stays as it is."""

    @extend_schema(request=None, responses={201: AnnualReportSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            report = self.locked(request, organization_pk, pk)
            if report.status != AnnualReport.Status.PUBLISHED:
                raise ApiException("not_published", "Only a published report is amended.", 409)
            if AnnualReport.objects.filter(amends=report).exists():
                raise ApiException("already_amended", "This version already has a newer one.", 409)
            newer = AnnualReport.objects.create(
                organization=report.organization,
                period_start=report.period_start,
                period_end=report.period_end,
                version=report.version + 1,
                amends=report,
                narrative=report.narrative,
                created_by=request.user,
            )
        return self.reply(request, newer, status.HTTP_201_CREATED)


class ExportReportView(APIView):
    """GET .../annual-reports/{id}/export.csv or export.pdf: the report as a file, for whoever may read
    it."""

    permission_classes = [PublicReads]
    public_actions = ("get",)
    kind = "csv"

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request, organization_pk, pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        report = get_object_or_404(readable(request.user, organization), pk=pk)
        if self.kind not in ("csv", "pdf"):
            raise Http404
        rows = reports.lines(organization.name, report, shown(report, request.user)["figures"])
        if self.kind == "pdf":
            response = HttpResponse(reports.as_pdf(rows), content_type="application/pdf")
        else:
            response = HttpResponse(reports.as_csv(rows), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="financial-report-{report.period_end}.{self.kind}"'
        )
        return response
