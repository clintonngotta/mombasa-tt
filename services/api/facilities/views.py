from django.db import IntegrityError, transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from organizations.access import (
    effective_permissions,
    lock_organization,
    require_membership,
    require_permission,
)
from organizations.models import Organization
from organizations.permissions import Permission

from .models import MAX_ACTIVE_TABLES, MAX_ACTIVE_VENUES, Table, Venue
from .serializers import TableSerializer, VenueSerializer

MANAGE = Permission.FACILITIES_MANAGE


def _save(serializer, field: str, message: str, **extra):
    """Save, turning the 'one active name' database constraint into a field error."""
    try:
        with transaction.atomic():
            return serializer.save(**extra)
    except IntegrityError as error:
        raise ValidationError({field: message}) from error


class VenueViewSet(viewsets.GenericViewSet):
    """Venues and tables of one organization (REQ-007). Members see the venues in use; holders of
    facilities.manage add, rename and switch venues and tables off or back on, and see them all."""

    serializer_class = VenueSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_organization(self) -> Organization:
        return get_object_or_404(Organization, pk=self.kwargs["organization_pk"])

    def _staff_venue(self, request, organization: Organization, pk) -> Venue:
        """Lock the organization, check the permission, and return one of its venues."""
        lock_organization(organization)
        require_permission(request.user, organization, MANAGE)
        return get_object_or_404(Venue, pk=pk, organization=organization)

    @staticmethod
    def _reply(venue: Venue, code=status.HTTP_200_OK) -> Response:
        venue = Venue.objects.prefetch_related("tables").get(pk=venue.pk)
        return Response(VenueSerializer(venue, context={"staff": True}).data, status=code)

    @extend_schema(responses={200: VenueSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_membership(request.user, organization)
        staff = MANAGE in effective_permissions(request.user, organization)
        venues = organization.venues.prefetch_related("tables")
        if not staff:
            venues = venues.filter(active=True)
        return Response(VenueSerializer(venues, many=True, context={"staff": staff}).data)

    @extend_schema(request=VenueSerializer, responses={201: VenueSerializer})
    def create(self, request, organization_pk):
        organization = self.get_organization()
        serializer = VenueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, MANAGE)
            self._ensure_room(organization)
            venue = _save(
                serializer, "name", "Another venue already has this name.", organization=organization
            )
        return self._reply(venue, status.HTTP_201_CREATED)

    @extend_schema(request=VenueSerializer, responses={200: VenueSerializer})
    def partial_update(self, request, organization_pk, pk):
        organization = self.get_organization()
        with transaction.atomic():
            venue = self._staff_venue(request, organization, pk)
            serializer = VenueSerializer(venue, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            if serializer.validated_data.get("active") and not venue.active:
                self._ensure_room(organization)
            venue = _save(serializer, "name", "Another venue already has this name.")
        return self._reply(venue)

    @extend_schema(request=TableSerializer, responses={201: VenueSerializer})
    def add_table(self, request, organization_pk, pk):
        """Add a table at the end of the venue's playing order. Replies with the whole venue."""
        organization = self.get_organization()
        serializer = TableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            venue = self._staff_venue(request, organization, pk)
            self._ensure_table_room(venue)
            last = venue.tables.aggregate(last=Max("position"))["last"]
            _save(
                serializer,
                "label",
                "Another table here already has this label.",
                venue=venue,
                position=0 if last is None else last + 1,
            )
        return self._reply(venue, status.HTTP_201_CREATED)

    @extend_schema(request=TableSerializer, responses={200: VenueSerializer})
    def update_table(self, request, organization_pk, pk, table_pk):
        organization = self.get_organization()
        with transaction.atomic():
            venue = self._staff_venue(request, organization, pk)
            table = get_object_or_404(Table, pk=table_pk, venue=venue)
            serializer = TableSerializer(table, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            if serializer.validated_data.get("active") and not table.active:
                self._ensure_table_room(venue)
            _save(serializer, "label", "Another table here already has this label.")
        return self._reply(venue)

    @staticmethod
    def _ensure_room(organization: Organization) -> None:
        if organization.venues.filter(active=True).count() >= MAX_ACTIVE_VENUES:
            raise ApiException(
                "too_many_venues",
                f"An organization can have {MAX_ACTIVE_VENUES} venues in use. Switch one off first.",
                409,
            )

    @staticmethod
    def _ensure_table_room(venue: Venue) -> None:
        if venue.tables.filter(active=True).count() >= MAX_ACTIVE_TABLES:
            raise ApiException(
                "too_many_tables",
                f"A venue can have {MAX_ACTIVE_TABLES} tables in use. Switch one off first.",
                409,
            )
