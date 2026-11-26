"""Money from outside the membership (REQ-051): the club's own list of sources, the income recorded
under them, and totals split into internal (members) and external (by source).

Finance managers keep the sources and record income by choosing one, never by typing free text. A source
that has income is switched off rather than deleted. Finance staff read; members see only what the annual
report publishes.
"""

from collections import defaultdict

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Sum
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.access import require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from .models import ExternalIncome, ExternalSource, Payment

VIEW = (Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE)
MANAGE = Permission.FINANCES_MANAGE
MAX_SOURCES = 60
MAX_ROWS = 300


class StrictExternalFields(serializers.Serializer):
    """Refuses fields it doesn't know."""

    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", None) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class ExternalSourceSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=80, trim_whitespace=True)
    used = serializers.BooleanField(
        read_only=True, help_text="It has income recorded, so it can't be deleted."
    )

    class Meta:
        model = ExternalSource
        fields = ["id", "name", "active", "used"]
        read_only_fields = ["id", "used"]

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        return attrs


class ExternalIncomeSerializer(serializers.ModelSerializer):
    """Income from outside, as finance staff see it. The source is chosen by id from the club's list."""

    source_id = serializers.UUIDField()
    source_name = serializers.CharField(source="source.name", read_only=True)
    description = serializers.CharField(
        max_length=200, trim_whitespace=True, allow_blank=True, required=False
    )
    reference = serializers.CharField(max_length=60, trim_whitespace=True, allow_blank=True, required=False)
    amount_minor = serializers.IntegerField(min_value=1, max_value=1_000_000_000)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False, default="KES")
    request_key = serializers.UUIDField(write_only=True, help_text="Sent again, it records nothing new.")
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = ExternalIncome
        fields = [
            "id",
            "source_id",
            "source_name",
            "description",
            "amount_minor",
            "currency",
            "received_on",
            "reference",
            "request_key",
            "reversed",
            "reversal_reason",
            "created_at",
        ]
        read_only_fields = ["id", "reversal_reason", "created_at"]

    def get_reversed(self, income) -> bool:
        return income.reversed_at is not None

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: "This field isn't accepted." for name in sorted(unknown)}
            )
        if attrs["received_on"] > timezone.localdate():
            raise serializers.ValidationError({"received_on": "Record money once it has been received."})
        return attrs


class ReverseIncomeSerializer(StrictExternalFields):
    reason = serializers.CharField(max_length=300, trim_whitespace=True)


class SourceTotalSerializer(serializers.Serializer):
    source_id = serializers.UUIDField()
    source_name = serializers.CharField()
    amount_minor = serializers.IntegerField()


class IncomeTotalsSerializer(serializers.Serializer):
    """Money received in the period, per currency: from members, from outside, and outside by source."""

    currency = serializers.CharField()
    internal_minor = serializers.IntegerField()
    external_minor = serializers.IntegerField()
    total_minor = serializers.IntegerField()
    by_source = SourceTotalSerializer(many=True)


def _org(request, organization_pk, *permissions) -> Organization:
    organization = get_object_or_404(Organization, pk=organization_pk)
    require_permission(request.user, organization, *permissions)
    return organization


def _shown(source) -> dict:
    used = getattr(source, "has_income", None)
    if used is None:
        used = source.income.exists()
    return {"id": source.pk, "name": source.name, "active": source.active, "used": used}


def _dates(request) -> dict:
    """`from` and `to` (dates, inclusive) as a filter on received_on; a bad date is a 400."""
    found = {}
    for param, lookup in (("from", "received_on__gte"), ("to", "received_on__lte")):
        value = request.query_params.get(param)
        if value:
            try:
                found[lookup] = serializers.DateField().to_internal_value(value)
            except serializers.ValidationError as error:
                raise serializers.ValidationError({param: "Give a date as YYYY-MM-DD."}) from error
    return found


class ExternalSourcesView(APIView):
    """GET/POST /organizations/{org}/finance/external-sources/: the club's list of where outside money
    comes from. Finance staff read it; finance managers add to it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ExternalSourceSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = _org(request, organization_pk, *VIEW)
        # One query for the list, whether each source has income included.
        sources = organization.external_sources.annotate(
            has_income=Exists(ExternalIncome.objects.filter(source=OuterRef("pk")))
        )
        return Response([_shown(source) for source in sources[:MAX_SOURCES]])

    @extend_schema(request=ExternalSourceSerializer, responses={201: ExternalSourceSerializer})
    def post(self, request, organization_pk):
        organization = _org(request, organization_pk, MANAGE)
        body = ExternalSourceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        name = body.validated_data["name"]
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=organization.pk)
            if organization.external_sources.count() >= MAX_SOURCES:
                raise ApiException("too_many_sources", f"Keep the list to {MAX_SOURCES} sources.", 409)
            if (
                organization.external_sources.annotate(lower=Lower("name"))
                .filter(lower=name.lower())
                .exists()
            ):
                raise serializers.ValidationError({"name": "That source is already on the list."})
            source = ExternalSource.objects.create(
                organization=organization, name=name, created_by=request.user
            )
        return Response(_shown(source), status=status.HTTP_201_CREATED)


class ExternalSourceView(APIView):
    """PATCH/DELETE /organizations/{org}/finance/external-sources/{id}/: rename a source or switch it
    off or on. Only a source with no income is deleted; one that was used is switched off instead."""

    permission_classes = [IsAuthenticated]

    def source(self, request, organization_pk, pk) -> ExternalSource:
        organization = _org(request, organization_pk, MANAGE)
        return get_object_or_404(ExternalSource.objects.select_for_update(), organization=organization, pk=pk)

    @extend_schema(request=ExternalSourceSerializer, responses={200: ExternalSourceSerializer})
    def patch(self, request, organization_pk, pk):
        with transaction.atomic():
            source = self.source(request, organization_pk, pk)
            body = ExternalSourceSerializer(source, data=request.data, partial=True)
            body.is_valid(raise_exception=True)
            data = body.validated_data
            if "name" in data and data["name"].lower() != source.name.lower():
                taken = ExternalSource.objects.filter(organization=source.organization_id).annotate(
                    lower=Lower("name")
                )
                if taken.filter(lower=data["name"].lower()).exists():
                    raise serializers.ValidationError({"name": "That source is already on the list."})
            for name, value in data.items():
                setattr(source, name, value)
            source.save()
        return Response(_shown(source))

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        with transaction.atomic():
            source = self.source(request, organization_pk, pk)
            if source.income.exists():
                raise ApiException(
                    "source_used", "This source has income recorded. Switch it off instead.", 409
                )
            source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExternalIncomeView(APIView):
    """GET/POST /organizations/{org}/finance/external-income/: income from outside the membership,
    latest first; `?source=`, `?from=` and `?to=` narrow it. Finance managers record it by choosing one
    of the club's active sources."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("source", str),
            OpenApiParameter("from", str, description="YYYY-MM-DD"),
            OpenApiParameter("to", str, description="YYYY-MM-DD"),
        ],
        responses={200: ExternalIncomeSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = _org(request, organization_pk, *VIEW)
        found = organization.external_income.select_related("source").filter(**_dates(request))
        if source := request.query_params.get("source"):
            try:
                found = found.filter(source_id=serializers.UUIDField().to_internal_value(source))
            except serializers.ValidationError as error:
                raise serializers.ValidationError({"source": "Choose one of your sources."}) from error
        return Response(ExternalIncomeSerializer(found[:MAX_ROWS], many=True).data)

    @extend_schema(request=ExternalIncomeSerializer, responses={201: ExternalIncomeSerializer})
    def post(self, request, organization_pk):
        organization = _org(request, organization_pk, MANAGE)
        body = ExternalIncomeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        source = ExternalSource.objects.filter(organization=organization, pk=data.pop("source_id")).first()
        if source is None or not source.active:
            raise serializers.ValidationError({"source_id": "Choose one of your active sources."})
        existing = ExternalIncome.objects.filter(
            organization=organization, request_key=data["request_key"]
        ).first()
        if existing is None:
            try:
                with transaction.atomic():
                    existing = ExternalIncome.objects.create(
                        organization=organization, source=source, recorded_by=request.user, **data
                    )
            except IntegrityError:  # the same request arrived twice at once
                existing = ExternalIncome.objects.get(
                    organization=organization, request_key=data["request_key"]
                )
            else:
                return Response(ExternalIncomeSerializer(existing).data, status=status.HTTP_201_CREATED)
        return Response(ExternalIncomeSerializer(existing).data, status=status.HTTP_200_OK)


class ReverseExternalIncomeView(APIView):
    """POST .../finance/external-income/{id}/reverse/: income recorded in error stays, marked reversed
    with who did it and why, and counts for nothing."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReverseIncomeSerializer, responses={200: ExternalIncomeSerializer})
    def post(self, request, organization_pk, pk):
        organization = _org(request, organization_pk, MANAGE)
        body = ReverseIncomeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            income = get_object_or_404(
                ExternalIncome.objects.select_for_update(of=("self",)).select_related("source"),
                organization=organization,
                pk=pk,
            )
            if income.reversed_at:
                raise ApiException("already_reversed", "This income was already reversed.", 409)
            income.reversed_at, income.reversed_by = timezone.now(), request.user
            income.reversal_reason = body.validated_data["reason"]
            income.save(update_fields=["reversed_at", "reversed_by", "reversal_reason"])
        return Response(ExternalIncomeSerializer(income).data)


class IncomeTotalsView(APIView):
    """GET /organizations/{org}/finance/income-totals/: what was received between `from` and `to`,
    per currency: from members (internal), from outside (external), and external by source. Reversed
    payments and income are left out."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="YYYY-MM-DD"),
            OpenApiParameter("to", str, description="YYYY-MM-DD"),
        ],
        responses={200: IncomeTotalsSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = _org(request, organization_pk, *VIEW)
        dates = _dates(request)
        internal = dict(
            Payment.objects.filter(organization=organization, reversed_at__isnull=True, **dates)
            .values("currency")
            .annotate(total=Sum("amount_minor"))
            .values_list("currency", "total")
        )
        external: dict = defaultdict(list)
        rows = (
            ExternalIncome.objects.filter(organization=organization, reversed_at__isnull=True, **dates)
            .values("currency", "source_id", "source__name")
            .annotate(total=Sum("amount_minor"))
            .order_by("source__name")
        )
        for row in rows:
            external[row["currency"]].append(
                {
                    "source_id": row["source_id"],
                    "source_name": row["source__name"],
                    "amount_minor": row["total"],
                }
            )
        out = []
        for currency in sorted(set(internal) | set(external)) or ["KES"]:
            outside = sum(row["amount_minor"] for row in external[currency])
            inside = internal.get(currency, 0)
            out.append(
                {
                    "currency": currency,
                    "internal_minor": inside,
                    "external_minor": outside,
                    "total_minor": inside + outside,
                    "by_source": external[currency],
                }
            )
        return Response(IncomeTotalsSerializer(out, many=True).data)
