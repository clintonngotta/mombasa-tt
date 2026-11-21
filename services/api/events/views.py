"""The events listing and external event submissions (REQ-042, TASK-080)."""

import uuid
from datetime import date

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.permissions import is_platform_super_admin
from notifications import triggers
from organizations.access import require_permission
from organizations.models import Organization
from organizations.permissions import Permission

from . import listing
from .models import ExternalEvent, LinkReport
from .serializers import (
    ExternalEventSerializer,
    LinkReportSerializer,
    ListedEventSerializer,
    MarkLiveSerializer,
    ReviewSerializer,
)

SUBMIT = Permission.ANNOUNCEMENTS_MANAGE


def _date(params, name):
    raw = params.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise ValidationError({name: "Use YYYY-MM-DD."}) from error


class EventListingView(APIView):
    """GET /events/: the public listing of table tennis events, on Coast TT and elsewhere."""

    permission_classes = [AllowAny]
    public_actions = ("get",)  # signed-out reads are held to the visitors' allowance (core/throttling.py)

    @extend_schema(
        parameters=[
            OpenApiParameter("when", str, enum=["upcoming", "past"]),
            OpenApiParameter("from", date, description="Events still on from this day (calendar view)"),
            OpenApiParameter("to", date, description="Events starting by this day"),
            OpenApiParameter("town", str),
            OpenApiParameter("category", str),
            OpenApiParameter("host", str, description="The host or submitting club's id"),
            OpenApiParameter("ours", bool, description="Only the caller's clubs"),
        ],
        responses={200: ListedEventSerializer(many=True)},
    )
    def get(self, request):
        params = request.query_params
        host = params.get("host") or None
        if host:
            try:
                host = uuid.UUID(host)
            except ValueError as error:
                raise ValidationError({"host": "Choose a club."}) from error
        items = listing.listing(
            request.user,
            when=params.get("when"),
            start=_date(params, "from"),
            end=_date(params, "to"),
            town=params.get("town", "").strip(),
            category=params.get("category", "").strip(),
            host=host,
            ours=params.get("ours") in ("true", "1"),
        )
        return Response(ListedEventSerializer(items[:300], many=True).data)


class ClubExternalEventsView(APIView):
    """A club's external event submissions, for its staff with announcements.manage."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ExternalEventSerializer(many=True)})
    def get(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, SUBMIT)
        return Response(ExternalEventSerializer(organization.external_events.all(), many=True).data)

    @extend_schema(request=ExternalEventSerializer, responses={201: ExternalEventSerializer})
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, SUBMIT)
        serializer = ExternalEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(submitted_by_org=organization, submitted_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class _SubmissionView(APIView):
    permission_classes = [IsAuthenticated]

    def _event(self, request, organization_pk, pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, SUBMIT)
        return get_object_or_404(organization.external_events, pk=pk)


class ClubExternalEventView(_SubmissionView):
    """Change a submission: details go back for review; postponing or cancelling doesn't."""

    @extend_schema(request=ExternalEventSerializer, responses={200: ExternalEventSerializer})
    def patch(self, request, organization_pk, pk):
        event = self._event(request, organization_pk, pk)
        serializer = ExternalEventSerializer(event, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        details = set(serializer.validated_data) - {"status"}
        if details and event.review != ExternalEvent.Review.PENDING:
            serializer.validated_data["review"] = ExternalEvent.Review.PENDING
        serializer.save()
        return Response(serializer.data)


class MarkLiveView(_SubmissionView):
    @extend_schema(request=MarkLiveSerializer, responses={200: ExternalEventSerializer})
    def post(self, request, organization_pk, pk):
        """The organizer says it's on now (or no longer)."""
        event = self._event(request, organization_pk, pk)
        body = MarkLiveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        event.marked_live = body.validated_data["live"]
        event.save(update_fields=["marked_live"])
        return Response(ExternalEventSerializer(event).data)


def _curator(request):
    if not is_platform_super_admin(request.user):
        raise PermissionDenied("Only the platform's curators review events.")


class ReviewQueueView(APIView):
    """External events waiting for review, and reported links, for the platform's curators."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ExternalEventSerializer(many=True)})
    def get(self, request):
        _curator(request)
        waiting = ExternalEvent.objects.filter(
            review=ExternalEvent.Review.PENDING
        ) | ExternalEvent.objects.filter(link_reports__isnull=False).exclude(live_url="")
        return Response(
            ExternalEventSerializer(waiting.distinct().select_related("submitted_by_org"), many=True).data
        )


class CuratorActionView(APIView):
    permission_classes = [IsAuthenticated]
    action = ""

    @extend_schema(request=ReviewSerializer, responses={200: ExternalEventSerializer})
    def post(self, request, pk):
        _curator(request)
        body = ReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            event = get_object_or_404(ExternalEvent.objects.select_for_update(), pk=pk)
            if self.action == "remove_link":
                event.live_url = ""
                event.marked_live = False
                event.link_reports.all().delete()
            else:
                if self.action == "reject" and not body.validated_data.get("note"):
                    raise ValidationError({"note": "Say why, for the club that submitted it."})
                event.review = (
                    ExternalEvent.Review.APPROVED
                    if self.action == "approve"
                    else ExternalEvent.Review.REJECTED
                )
                event.review_note = body.validated_data.get("note", "")
                event.reviewed_by = request.user
                event.reviewed_at = timezone.now()
            event.save()
            if self.action != "remove_link":
                triggers.external_event_reviewed(event)
        return Response(ExternalEventSerializer(event).data)


class ReportLinkView(APIView):
    """Report an external event's live link. Once per person."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=LinkReportSerializer, responses={204: None})
    def post(self, request, pk):
        event = get_object_or_404(ExternalEvent, pk=pk, review=ExternalEvent.Review.APPROVED)
        if not event.live_url:
            raise ApiException("no_link", "This event has no live link.", 409)
        body = LinkReportSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                LinkReport.objects.create(
                    event=event, user=request.user, reason=body.validated_data["reason"]
                )
        except IntegrityError:
            pass  # already reported by this person
        return Response(status=status.HTTP_204_NO_CONTENT)
