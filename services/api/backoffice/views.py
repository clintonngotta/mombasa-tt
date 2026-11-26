"""The platform's back office (REQ-056): what a platform super admin runs from /admin in the app.

Every route here is for platform super admins alone, checked on the server for each request; everyone
else is told it doesn't exist. Changes to accounts and the place catalogue are written to the log with
who made them."""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import GUEST_EMAIL_DOMAIN, User
from competitions.models import Tournament
from core import geography
from core.exceptions import ApiException
from core.models import City, Country, Region
from core.pagination import StandardPagination, search_term
from core.permissions import is_platform_super_admin
from events.models import ExternalEvent
from organizations.models import Membership, Organization
from organizations.permissions import RoleKey

from .serializers import (
    AccountChangeSerializer,
    AccountSerializer,
    CountryChangeSerializer,
    OverviewSerializer,
    PlaceInputSerializer,
    PlatformCitySerializer,
    PlatformCountrySerializer,
    PlatformOrganizationSerializer,
    PlatformRegionSerializer,
)

logger = logging.getLogger(__name__)
MAX_SEARCH = 80


class IsPlatformSuperAdmin(BasePermission):
    """Not found for everyone but a platform super admin, so the back office can't be probed."""

    def has_permission(self, request, view):
        if not is_platform_super_admin(request.user):
            raise Http404
        return True


class PlatformView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformSuperAdmin]


def accounts():
    """People's accounts: guests entered by club staff have none of their own."""
    return User.objects.exclude(email__endswith="@" + GUEST_EMAIL_DOMAIN)


def record(request, what: str, **fields):
    logger.info(what, extra={"actor": str(request.user.pk), **fields})


class OverviewView(PlatformView):
    @extend_schema(responses={200: OverviewSerializer})
    def get(self, request):
        people = accounts().aggregate(
            accounts=Count("pk"),
            accounts_new=Count("pk", filter=Q(date_joined__gte=timezone.now() - timedelta(days=30))),
            accounts_inactive=Count("pk", filter=Q(is_active=False)),
            platform_admins=Count("pk", filter=Q(is_superuser=True, is_active=True)),
        )
        kinds = dict(Organization.objects.values_list("kind").annotate(n=Count("pk")))
        statuses = dict(Tournament.objects.values_list("status").annotate(n=Count("pk")))
        data = {
            **people,
            "organizations": {kind: kinds.get(kind, 0) for kind in Organization.Kind.values},
            "tournaments": {state: statuses.get(state, 0) for state in Tournament.Status.values},
            "tournaments_awaiting_approval": Tournament.objects.filter(
                status=Tournament.Status.DRAFT, approval_status=Tournament.Approval.PENDING
            ).count(),
            "events_awaiting_review": ExternalEvent.objects.filter(
                review=ExternalEvent.Review.PENDING
            ).count(),
        }
        return Response(OverviewSerializer(data).data)


SEARCH = OpenApiParameter(
    "search", str, description="Part of a name, email or phone (80 characters at most)."
)


@extend_schema(
    parameters=[
        SEARCH,
        OpenApiParameter("show", str, enum=["all", "admins", "inactive"], description="Default: all."),
    ]
)
class AccountsView(ListAPIView):
    """GET /platform/accounts/: every account, newest first."""

    permission_classes = PlatformView.permission_classes
    serializer_class = AccountSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        found = accounts().annotate(
            organizations=Count("memberships", filter=Q(memberships__status=Membership.Status.ACTIVE))
        )
        term = search_term(self.request)[:MAX_SEARCH]
        if term:
            found = found.filter(
                Q(display_name__icontains=term) | Q(email__icontains=term) | Q(phone__icontains=term)
            )
        show = self.request.query_params.get("show")
        if show == "admins":
            found = found.filter(is_superuser=True)
        elif show == "inactive":
            found = found.filter(is_active=False)
        return found.order_by("-date_joined", "pk")


class AccountView(PlatformView):
    """PATCH /platform/accounts/{id}/: switch an account off or on, or give or take platform authority.
    Nobody changes their own account here, so the platform always keeps at least one super admin."""

    @extend_schema(request=AccountChangeSerializer, responses={200: AccountSerializer})
    @transaction.atomic
    def patch(self, request, pk):
        account = get_object_or_404(accounts().select_for_update(), pk=pk)
        serializer = AccountChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if account.pk == request.user.pk:
            raise ApiException("own_account", "Ask another super admin to change your own account.", 409)
        changed = []
        if "is_active" in data and data["is_active"] != account.is_active:
            account.is_active = data["is_active"]
            changed.append("is_active")
        if "is_platform_admin" in data and data["is_platform_admin"] != account.is_superuser:
            if data["is_platform_admin"] and not (account.is_verified and account.has_usable_password()):
                raise ApiException(
                    "account_not_ready",
                    "Only a verified account with a password can be a super admin.",
                    409,
                )
            # Platform authority is the superuser flag; the staff flag goes with it.
            account.is_superuser = account.is_staff = data["is_platform_admin"]
            changed += ["is_superuser", "is_staff"]
        if changed:
            account.save(update_fields=changed)
            record(
                request,
                "platform.account_changed",
                account=str(account.pk),
                is_active=account.is_active,
                is_platform_admin=account.is_superuser,
            )
        account.organizations = account.memberships.filter(status=Membership.Status.ACTIVE).count()
        return Response(AccountSerializer(account).data)


@extend_schema(
    parameters=[
        OpenApiParameter("search", str, description="Part of a name, town or region."),
        OpenApiParameter("kind", str, enum=Organization.Kind.values),
    ]
)
class OrganizationsView(ListAPIView):
    """GET /platform/organizations/: every club, facility, body and coaching desk, with its admin."""

    permission_classes = PlatformView.permission_classes
    serializer_class = PlatformOrganizationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        admin = Membership.objects.filter(
            organization=OuterRef("pk"),
            status=Membership.Status.ACTIVE,
            roles__key=RoleKey.ADMIN,
            user__is_active=True,
        ).order_by("joined_at")
        found = Organization.objects.annotate(
            members=Count("memberships", filter=Q(memberships__status=Membership.Status.ACTIVE)),
            admin_name=Subquery(admin.values("user__display_name")[:1]),
        )
        term = search_term(self.request)[:MAX_SEARCH]
        if term:
            found = found.filter(
                Q(name__icontains=term) | Q(town__icontains=term) | Q(region__icontains=term)
            )
        kind = self.request.query_params.get("kind")
        if kind in Organization.Kind.values:
            found = found.filter(kind=kind)
        return found.order_by("name", "pk")


def country_or_404(code: str) -> Country:
    return get_object_or_404(Country, pk=code.upper())


def catalogue(country: Country):
    country = Country.objects.prefetch_related("regions__cities").get(pk=country.pk)
    return PlatformCountrySerializer(country).data


def named(request) -> str:
    serializer = PlaceInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["name"]


def taken(what: str):
    return ApiException("place_exists", f"That {what} is already on the list.", 409)


class CountryView(PlatformView):
    """The place catalogue of one country, with the ids the back office edits by."""

    @extend_schema(responses={200: PlatformCountrySerializer})
    def get(self, request, code):
        return Response(catalogue(country_or_404(code)))

    @extend_schema(request=CountryChangeSerializer, responses={200: PlatformCountrySerializer})
    def patch(self, request, code):
        country = country_or_404(code)
        serializer = CountryChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        country.catalogue_only = serializer.validated_data["catalogue_only"]
        country.save(update_fields=["catalogue_only"])
        record(request, "platform.country_changed", country=country.pk, catalogue_only=country.catalogue_only)
        return Response(catalogue(country))


class RegionsView(PlatformView):
    @extend_schema(request=PlaceInputSerializer, responses={201: PlatformRegionSerializer})
    def post(self, request, code):
        country = country_or_404(code)
        try:
            with transaction.atomic():
                region = Region.objects.create(country=country, name=named(request))
        except IntegrityError as error:
            raise taken("region") from error
        record(request, "platform.region_added", country=country.pk, region=region.pk)
        return Response(PlatformRegionSerializer(region).data, status=status.HTTP_201_CREATED)


class RegionView(PlatformView):
    @extend_schema(request=PlaceInputSerializer, responses={200: PlatformRegionSerializer})
    def patch(self, request, pk):
        name = named(request)
        try:
            with transaction.atomic():
                region = get_object_or_404(Region.objects.select_for_update(), pk=pk)
                previous = Region(pk=region.pk, name=region.name, country_id=region.country_id)
                region.name = name
                region.save(update_fields=["name"])
                geography.region_changed(previous, region)
        except IntegrityError as error:
            raise taken("region") from error
        record(request, "platform.region_renamed", region=region.pk)
        return Response(PlatformRegionSerializer(region).data)

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request, pk):
        region = get_object_or_404(Region.objects.select_for_update(), pk=pk)
        if geography.region_in_use(region):
            raise ApiException(
                "place_in_use", "Towns, clubs or players are in this region. Rename it instead.", 409
            )
        try:
            region.delete()
        except ProtectedError as error:
            raise ApiException("place_in_use", "This region is still in use.", 409) from error
        record(request, "platform.region_removed", region=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CitiesView(PlatformView):
    @extend_schema(request=PlaceInputSerializer, responses={201: PlatformCitySerializer})
    def post(self, request, pk):
        region = get_object_or_404(Region, pk=pk)
        try:
            with transaction.atomic():
                city = City.objects.create(region=region, name=named(request))
        except IntegrityError as error:
            raise taken("town") from error
        record(request, "platform.city_added", region=region.pk, city=city.pk)
        return Response(PlatformCitySerializer(city).data, status=status.HTTP_201_CREATED)


class CityView(PlatformView):
    @extend_schema(request=PlaceInputSerializer, responses={200: PlatformCitySerializer})
    def patch(self, request, pk):
        name = named(request)
        try:
            with transaction.atomic():
                city = get_object_or_404(
                    City.objects.select_for_update(of=("self",)).select_related("region"), pk=pk
                )
                previous = City(pk=city.pk, name=city.name, region=city.region)
                city.name = name
                city.save(update_fields=["name"])
                geography.city_changed(previous, city)
        except IntegrityError as error:
            raise taken("town") from error
        record(request, "platform.city_renamed", city=city.pk)
        return Response(PlatformCitySerializer(city).data)

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request, pk):
        city = get_object_or_404(City.objects.select_for_update(of=("self",)).select_related("region"), pk=pk)
        if geography.city_in_use(city):
            raise ApiException("place_in_use", "Clubs or players are in this town. Rename it instead.", 409)
        city.delete()
        record(request, "platform.city_removed", city=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
