"""Table bookings (REQ-021, TASK-036): players ask, the venue's staff decide."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination
from organizations.access import require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import bookings, profile
from .models import Booking, Table, Venue
from .serializers import ApproveTableBookingSerializer, TableBookingReasonSerializer, TableBookingSerializer


def bookable(user):
    """Venues a player may ask to book: facility branches they can find, and their own clubs' venues."""
    clubs = Membership.objects.active().filter(user=user).values("organization")
    return Venue.objects.filter(
        Q(pk__in=profile.findable(user).values("pk")) | Q(organization__in=clubs), active=True
    )


def _with(queryset):
    return queryset.select_related("venue__organization", "requester").prefetch_related("tables")


class MyBookingViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """The signed-in player's booking requests."""

    serializer_class = TableBookingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        return _with(Booking.objects.filter(requester=self.request.user)).order_by("-starts_at")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        venue = get_object_or_404(
            bookable(request.user).prefetch_related("opening_hours", "closures"), pk=data["venue_id"]
        )
        tables = list(Table.objects.filter(pk__in=data["table_ids"]))
        if len(tables) != len(set(data["table_ids"])):
            tables = []
        bookings.check_request(venue, tables, data["starts_at"], data["ends_at"])
        booking = Booking.objects.create(
            venue=venue,
            requester=request.user,
            starts_at=data["starts_at"],
            ends_at=data["ends_at"],
            note=data.get("note", ""),
        )
        booking.tables.set(tables)
        return Response(
            self.get_serializer(_with(Booking.objects.filter(pk=booking.pk)).get()).data, status=201
        )

    @extend_schema(request=TableBookingReasonSerializer, responses={200: TableBookingSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        body = TableBookingReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        bookings.cancel(booking, request.user, body.validated_data.get("reason", ""))
        return Response(self.get_serializer(self.get_queryset().get(pk=booking.pk)).data)


class ClubBookingViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Booking requests at the organization's venues, for staff with facilities.manage. Requested and
    approved are shown apart; nothing pending holds a table."""

    serializer_class = TableBookingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def organization(self):
        if not hasattr(self, "_organization"):
            self._organization = get_object_or_404(Organization, pk=self.kwargs["organization_pk"])
            require_permission(self.request.user, self._organization, Permission.FACILITIES_MANAGE)
        return self._organization

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        found = _with(Booking.objects.filter(venue__organization=self.organization()))
        if self.action == "list" and (wanted := self.request.query_params.get("status")):
            found = found.filter(status=wanted)
        return found

    @extend_schema(parameters=[OpenApiParameter("status", str, enum=Booking.Status.values)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _reply(self, booking):
        return Response(self.get_serializer(self.get_queryset().get(pk=booking.pk)).data)

    @extend_schema(request=ApproveTableBookingSerializer, responses={200: TableBookingSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, organization_pk=None, pk=None):
        body = ApproveTableBookingSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        booking = self.get_object()
        bookings.approve(booking, request.user, body.validated_data.get("fee_minor"))
        return self._reply(booking)

    @extend_schema(request=TableBookingReasonSerializer, responses={200: TableBookingSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request, organization_pk=None, pk=None):
        body = TableBookingReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        if not body.validated_data.get("reason"):
            raise ApiException("reason_required", "Say why, for the player who asked.", 400)
        booking = self.get_object()
        bookings.reject(booking, request.user, body.validated_data["reason"])
        return self._reply(booking)

    @extend_schema(request=TableBookingReasonSerializer, responses={200: TableBookingSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, organization_pk=None, pk=None):
        body = TableBookingReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        booking = self.get_object()
        bookings.cancel(booking, request.user, body.validated_data.get("reason", ""))
        return self._reply(booking)
