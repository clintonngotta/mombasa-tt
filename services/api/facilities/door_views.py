"""Prices, door visits and takings at facility branches (REQ-044, TASK-102)."""

import re
import uuid
from datetime import date
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.pagination import StandardPagination
from organizations.access import require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import door
from .models import Pass, Venue, Visit
from .serializers import (
    MyVisitSerializer,
    PassSerializer,
    RecordVisitSerializer,
    ReverseVisitSerializer,
    TakingsSerializer,
    VisitSerializer,
)

MANAGE = Permission.FACILITIES_MANAGE
MONTH = re.compile(r"^(\d{4})-(\d{2})$")


class BranchMixin:
    def venue(self) -> Venue:
        if not hasattr(self, "_venue"):
            organization = get_object_or_404(Organization, pk=self.kwargs["organization_pk"])
            require_permission(self.request.user, organization, MANAGE)
            self._venue = get_object_or_404(
                Venue.objects.select_related("organization"),
                pk=self.kwargs["venue_pk"],
                organization=organization,
            )
        return self._venue


class PassViewSet(BranchMixin, viewsets.GenericViewSet):
    """A branch's prices, for its facility staff. Players see the ones in use on the branch profile."""

    serializer_class = PassSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Pass.objects.none()
        return self.venue().passes.all()

    @extend_schema(responses={200: PassSerializer(many=True)})
    def list(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def create(self, request, *args, **kwargs):
        venue = self.venue()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(venue=venue)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        price = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        serializer = self.get_serializer(price, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class VisitViewSet(BranchMixin, viewsets.GenericViewSet):
    """The door screen of a branch: the day's visits, recording one, and reversing a mistake."""

    serializer_class = VisitSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Visit.objects.none()
        return self.venue().visits.select_related("pass_sold", "player", "recorded_by")

    @extend_schema(
        parameters=[OpenApiParameter("day", date, description="The branch's local day; today by default")],
        responses={200: VisitSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        raw = request.query_params.get("day")
        try:
            day = date.fromisoformat(raw) if raw else door.today_at(self.venue())
        except ValueError as error:
            raise ValidationError({"day": "Use YYYY-MM-DD."}) from error
        visits = self.get_queryset().filter(visited_on=day)
        return Response(self.get_serializer(visits, many=True).data)

    @extend_schema(request=RecordVisitSerializer, responses={201: VisitSerializer})
    def create(self, request, *args, **kwargs):
        venue = self.venue()
        body = RecordVisitSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        player = None
        if data.get("player_id"):
            player = get_object_or_404(get_user_model(), pk=data["player_id"], is_active=True)
        price = None
        if data.get("pass_id"):
            price = get_object_or_404(Pass, pk=data["pass_id"], venue=venue)
        visit = door.record(
            venue,
            request.user,
            pass_sold=price,
            player=player,
            walk_in_name=data.get("walk_in_name", ""),
            method=data["method"],
            reference=data.get("reference", ""),
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=visit.pk)).data, status=201)

    @extend_schema(request=ReverseVisitSerializer, responses={200: VisitSerializer})
    @action(detail=True, methods=["post"])
    def reverse(self, request, *args, **kwargs):
        """Reverse a visit recorded by mistake. The original stays, marked reversed with the reason."""
        visit = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        body = ReverseVisitSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        door.reverse(visit, request.user, body.validated_data["reason"])
        return Response(self.get_serializer(self.get_queryset().get(pk=visit.pk)).data)

    @extend_schema(
        parameters=[OpenApiParameter("player", str, description="The player's id")],
        responses={200: VisitSerializer(allow_null=True)},
    )
    @action(detail=False, url_path="active-pass")
    def active_pass(self, request, *args, **kwargs):
        """The pass this player holds here that covers today, if any: shown at the door."""
        venue = self.venue()
        if not request.query_params.get("player"):
            return JsonResponse(None, safe=False)
        try:
            player_id = uuid.UUID(request.query_params["player"])
        except ValueError as error:
            raise ValidationError({"player": "Choose a player."}) from error
        player = get_object_or_404(get_user_model(), pk=player_id)
        sale = door.active_pass(player, venue, door.today_at(venue))
        if sale is None:
            return JsonResponse(None, safe=False)  # JSON null: no pass covers today
        return Response(self.get_serializer(self.get_queryset().get(pk=sale.pk)).data)


class TakingsViewSet(viewsets.GenericViewSet):
    """What the facility's branches collected in a month (REQ-044), for those who see its finances."""

    serializer_class = TakingsSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("month", str, description="YYYY-MM; this month by default"),
            OpenApiParameter("venue", str, description="Only this branch"),
        ]
    )
    def list(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE)
        raw = request.query_params.get("month") or ""
        if raw:
            match = MONTH.match(raw)
            if not match or not 1 <= int(match.group(2)) <= 12:
                raise ValidationError({"month": "Use YYYY-MM."})
            year, month = int(match.group(1)), int(match.group(2))
        else:
            here = timezone.now().astimezone(ZoneInfo(organization.timezone))
            year, month = here.year, here.month
        visits = Visit.objects.filter(
            venue__organization=organization, visited_on__year=year, visited_on__month=month
        )
        if venue := request.query_params.get("venue"):
            try:
                visits = visits.filter(venue_id=uuid.UUID(venue))
            except ValueError as error:
                raise ValidationError({"venue": "Choose a branch."}) from error
        return Response(TakingsSerializer({"month": f"{year:04d}-{month:02d}", **door.takings(visits)}).data)


class MyVisitViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The signed-in player's own visits and passes at facilities, newest first."""

    serializer_class = MyVisitSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Visit.objects.none()
        return (
            Visit.objects.filter(player=self.request.user)
            .select_related("venue__organization", "pass_sold")
            .order_by("-visited_on", "-recorded_at")
        )
