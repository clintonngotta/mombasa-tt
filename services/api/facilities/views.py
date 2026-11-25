from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from activities.models import Activity
from competitions.models import Tournament
from core.exceptions import ApiException
from core.nearby import MAX_RESULTS, within
from core.pagination import StandardPagination, search_term
from organizations.access import (
    effective_permissions,
    lock_organization,
    require_membership,
    require_permission,
)
from organizations.models import Organization
from organizations.permissions import Permission
from training.models import ClubSession

from . import profile
from .models import MAX_ACTIVE_TABLES, MAX_ACTIVE_VENUES, Closure, OpeningHour, Table, TrainingHour, Venue
from .serializers import (
    BranchScheduleItemSerializer,
    FacilityProfileSerializer,
    FacilitySerializer,
    NearbyFacilitiesSerializer,
    NearbyFacilitySearchSerializer,
    TableSerializer,
    TrainingHourListSerializer,
    TrainingHourSerializer,
    VenueHoursSerializer,
    VenueSerializer,
)

MANAGE = Permission.FACILITIES_MANAGE
# How many of the nearest branches an "open now" search near a point looks through.
NEARBY_SCAN = 200


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
        venue = Venue.objects.prefetch_related("tables", "opening_hours", "closures").get(pk=venue.pk)
        return Response(VenueSerializer(venue, context={"staff": True}).data, status=code)

    @extend_schema(responses={200: VenueSerializer(many=True)})
    def list(self, request, organization_pk):
        organization = self.get_organization()
        require_membership(request.user, organization)
        staff = MANAGE in effective_permissions(request.user, organization)
        venues = organization.venues.prefetch_related("tables", "opening_hours", "closures")
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

    @extend_schema(request=VenueHoursSerializer, responses={200: VenueSerializer})
    def hours(self, request, organization_pk, pk):
        """Replace the venue's weekly opening hours and its closures together."""
        organization = self.get_organization()
        serializer = VenueHoursSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            venue = self._staff_venue(request, organization, pk)
            venue.opening_hours.all().delete()
            venue.closures.all().delete()
            OpeningHour.objects.bulk_create(
                OpeningHour(venue=venue, **hour) for hour in serializer.validated_data["hours"]
            )
            Closure.objects.bulk_create(
                Closure(venue=venue, **closure) for closure in serializer.validated_data["closures"]
            )
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


class TrainingHoursView(APIView):
    """The club's weekly training times. Any signed-in player reads them (they are on the club's profile);
    holders of training.manage replace the whole list."""

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _reply(organization: Organization) -> Response:
        hours = organization.training_hours.select_related("venue")
        return Response(TrainingHourSerializer(hours, many=True, context={"organization": organization}).data)

    @extend_schema(responses={200: TrainingHourSerializer(many=True)})
    def get(self, request, organization_pk):
        return self._reply(get_object_or_404(Organization, pk=organization_pk))

    @extend_schema(request=TrainingHourListSerializer, responses={200: TrainingHourSerializer(many=True)})
    def put(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        with transaction.atomic():
            lock_organization(organization)
            require_permission(request.user, organization, Permission.TRAINING_MANAGE)
            serializer = TrainingHourListSerializer(data=request.data, context={"organization": organization})
            serializer.is_valid(raise_exception=True)
            organization.training_hours.all().delete()
            TrainingHour.objects.bulk_create(
                TrainingHour(organization=organization, **hour) for hour in serializer.validated_data["hours"]
            )
        return self._reply(organization)


class FacilityViewSet(viewsets.ReadOnlyModelViewSet):
    """The facility finder (REQ-044): branches of facility organizations whose profile the caller may
    see, by place and by whether they are open now in the facility's own timezone."""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_serializer_class(self):
        return FacilityProfileSerializer if self.action == "retrieve" else FacilitySerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Venue.objects.none()
        return profile.with_profile(profile.findable(self.request.user)).order_by("name", "id")

    def filter_queryset(self, queryset):
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if term := search_term(self.request):
            queryset = queryset.filter(
                Q(name__icontains=term) | Q(organization__name__icontains=term) | Q(town__icontains=term)
            )
        if country := params.get("country", "").strip().upper():
            queryset = queryset.filter(country=country)
        if region := params.get("region", "").strip():
            queryset = queryset.filter(region__iexact=region)
        if city := params.get("city", "").strip():
            queryset = queryset.filter(town__iexact=city)
        if params.get("open_now") in ("true", "1"):
            now = timezone.now()
            queryset = [venue for venue in queryset if profile.is_open(venue, now)]
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Branch, facility or town"),
            OpenApiParameter("country", str, description="Country code, e.g. KE"),
            OpenApiParameter("region", str, description="Region, any letter case"),
            OpenApiParameter("city", str, description="City or town, any letter case"),
            OpenApiParameter("open_now", bool, description="Only branches open at this moment"),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @property
    def throttle_scope(self):
        # A distance search works harder than a list.
        return "nearby" if self.action == "nearby" else None

    @extend_schema(request=NearbyFacilitySearchSerializer, responses={200: NearbyFacilitiesSerializer})
    @action(detail=False, methods=["post"])
    def nearby(self, request):
        """Branches the caller may find with a map position inside `radius_m` of the given point,
        nearest first, at most 50. The point is sent in the body so the player's position stays out
        of URLs and logs."""
        search = NearbyFacilitySearchSerializer(data=request.data)
        search.is_valid(raise_exception=True)
        where = search.validated_data
        branches = self.get_queryset()
        if term := where.get("search"):
            branches = branches.filter(
                Q(name__icontains=term) | Q(organization__name__icontains=term) | Q(town__icontains=term)
            )
        found = within(branches, where["latitude"], where["longitude"], where["radius_m"])
        if where["open_now"]:
            # Opening hours are read in each facility's own timezone, so this is decided row by row,
            # over a bounded number of the nearest branches.
            now = timezone.now()
            open_ones = [venue for venue in found[:NEARBY_SCAN] if profile.is_open(venue, now)]
            count, results = len(open_ones), open_ones[:MAX_RESULTS]
        else:
            results = list(found[:MAX_RESULTS])
            count = len(results) if len(results) < MAX_RESULTS else found.count()
        return Response(NearbyFacilitiesSerializer({"count": count, "results": results}).data)

    @extend_schema(responses={200: BranchScheduleItemSerializer(many=True)})
    @action(detail=True)
    def schedule(self, request, pk=None):
        """What the branch has coming up, in date order: training slots any player may join, the
        facility's public activities, and tournaments held here."""
        venue = self.get_object()
        now = timezone.now()
        items = []
        sessions = ClubSession.objects.filter(
            tables__venue=venue,
            open_to_players=True,
            status=ClubSession.Status.SCHEDULED,
            ends_at__gt=now,
        ).distinct()
        for session in sessions:
            items.append(
                {
                    "kind": "training",
                    "id": session.id,
                    "title": session.title,
                    "starts_at": session.starts_at,
                    "ends_at": session.ends_at,
                }
            )
        activities = Activity.objects.filter(
            organization=venue.organization, public=True, status=Activity.Status.PUBLISHED, ends_at__gt=now
        )
        for activity in activities:
            items.append(
                {
                    "kind": "activity",
                    "id": activity.id,
                    "title": activity.title,
                    "starts_at": activity.starts_at,
                    "ends_at": activity.ends_at,
                }
            )
        shown = [Tournament.Status.PUBLISHED, Tournament.Status.IN_PROGRESS]
        for tournament in Tournament.objects.filter(venue=venue, status__in=shown):
            zone = ZoneInfo(tournament.timezone)
            ends = datetime.combine(tournament.ends_on + timedelta(days=1), time.min, tzinfo=zone)
            if ends <= now:
                continue
            items.append(
                {
                    "kind": "tournament",
                    "id": tournament.id,
                    "title": tournament.name,
                    "starts_at": datetime.combine(tournament.starts_on, time.min, tzinfo=zone),
                    "ends_at": ends,
                }
            )
        items.sort(key=lambda item: item["starts_at"])
        return Response(BranchScheduleItemSerializer(items, many=True).data)
