"""Club activities, answers and the club schedule (REQ-039, TASK-072)."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.pagination import StandardPagination
from notifications import triggers
from organizations.access import require_membership, require_permission
from organizations.models import Membership, Organization

from . import service
from .models import Activity, Rsvp
from .serializers import (
    AttendeeSerializer,
    CancelActivitySerializer,
    ClubActivitySerializer,
    RsvpRequestSerializer,
    ScheduleItemSerializer,
)

WHEN = OpenApiParameter("when", str, enum=["upcoming", "past"])


class ActivityViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """A club's activities. Holders of activities.manage create, edit, publish and cancel them; members
    of the audience see them once published and answer."""

    serializer_class = ClubActivitySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def organization(self) -> Organization:
        if not hasattr(self, "_organization"):
            self._organization = get_object_or_404(Organization, pk=self.kwargs["organization_pk"])
        return self._organization

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Activity.objects.none()
        activities = service.visible(self.request.user, self.organization()).prefetch_related("rsvps")
        if self.action == "list":
            now = timezone.now()
            if self.request.query_params.get("when") == "past":
                return activities.filter(ends_at__lte=now).order_by("-starts_at", "id")
            return activities.filter(ends_at__gt=now)
        return activities

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False) or self.request is None:
            return context
        organization = self.organization()
        context["member"] = service.is_member(self.request.user, organization)
        context["invited"] = set(
            Activity.invitees.through.objects.filter(
                user_id=self.request.user.pk, activity__organization=organization
            ).values_list("activity_id", flat=True)
        )
        return context

    def _staff(self) -> Organization:
        organization = self.organization()
        require_permission(self.request.user, organization, service.MANAGE)
        return organization

    def _invitees(self, organization, ids):
        if ids is None:
            return None
        members = set(
            Membership.objects.active()
            .filter(organization=organization, user__in=ids)
            .values_list("user_id", flat=True)
        )
        if set(ids) - members:
            raise ValidationError({"invitee_ids": "Only active members of the club can be invited."})
        return get_user_model().objects.filter(pk__in=members)

    def _reply(self, activity, code=status.HTTP_200_OK):
        fresh = Activity.objects.prefetch_related("rsvps").get(pk=activity.pk)
        return Response(self.get_serializer(fresh).data, status=code)

    @extend_schema(parameters=[WHEN])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        organization = self._staff()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        invitee_ids = data.pop("invitee_ids", None)
        project_id = data.pop("welfare_project_id", None)
        data["welfare_project"] = service.check_welfare_link(
            request.user,
            organization,
            project_id,
            changed=project_id is not None,
            audience=data.get("audience", Activity.Audience.MEMBERS),
            invitee_ids=invitee_ids,
            public=data.get("public", False),
        )
        invitees = self._invitees(organization, invitee_ids)
        activity = Activity.objects.create(organization=organization, created_by=request.user, **data)
        if invitees is not None and activity.audience == Activity.Audience.SELECTED:
            activity.invitees.set(invitees)
        return self._reply(activity, status.HTTP_201_CREATED)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        organization = self._staff()
        activity = get_object_or_404(
            Activity.objects.select_for_update(), pk=kwargs["pk"], organization=organization
        )
        if activity.status == Activity.Status.CANCELLED:
            raise ApiException("activity_cancelled", "A cancelled activity stays as it was.", 409)
        serializer = self.get_serializer(activity, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        invitee_ids = data.pop("invitee_ids", None)
        project_id = data.pop("welfare_project_id", activity.welfare_project_id)
        audience = data.get("audience", activity.audience)
        chosen = invitee_ids
        if chosen is None and audience == Activity.Audience.SELECTED:
            chosen = list(activity.invitees.values_list("pk", flat=True))
        data["welfare_project"] = service.check_welfare_link(
            request.user,
            organization,
            project_id,
            audience=audience,
            invitee_ids=chosen,
            public=data.get("public", activity.public),
            changed=project_id != activity.welfare_project_id,
        )
        invitees = self._invitees(organization, invitee_ids)
        if (
            "capacity" in data
            and data["capacity"] is not None
            and data["capacity"] < service.going_count(activity)
        ):
            raise ApiException("capacity_below_going", "More people are already going than that.", 409)
        moved = activity.status == Activity.Status.PUBLISHED and any(
            key in data and data[key] != getattr(activity, key) for key in ("starts_at", "ends_at", "place")
        )
        for key, value in data.items():
            setattr(activity, key, value)
        activity.save()
        if moved:
            triggers.activity_news(activity, "changed")
        if activity.audience == Activity.Audience.MEMBERS:
            activity.invitees.clear()
        elif invitees is not None:
            activity.invitees.set(invitees)
        return self._reply(activity)

    @extend_schema(request=None, responses={200: ClubActivitySerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def publish(self, request, *args, **kwargs):
        """Publish a draft: the audience sees it and can answer."""
        organization = self._staff()
        activity = get_object_or_404(
            Activity.objects.select_for_update(), pk=kwargs["pk"], organization=organization
        )
        if activity.status == Activity.Status.CANCELLED:
            raise ApiException("activity_cancelled", "A cancelled activity stays cancelled.", 409)
        if activity.status == Activity.Status.DRAFT:
            activity.status = Activity.Status.PUBLISHED
            activity.published_at = timezone.now()
            activity.save(update_fields=["status", "published_at"])
            triggers.activity_news(activity, "published")
        return self._reply(activity)

    @extend_schema(request=CancelActivitySerializer, responses={200: ClubActivitySerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, *args, **kwargs):
        """Cancel with a reason. The record stays, with the answers it had."""
        organization = self._staff()
        activity = get_object_or_404(
            Activity.objects.select_for_update(), pk=kwargs["pk"], organization=organization
        )
        body = CancelActivitySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        if activity.status != Activity.Status.CANCELLED:
            activity.status = Activity.Status.CANCELLED
            activity.cancel_reason = body.validated_data["reason"]
            activity.cancelled_at = timezone.now()
            activity.save(update_fields=["status", "cancel_reason", "cancelled_at"])
            if activity.published_at:
                triggers.activity_news(activity, "cancelled")
        return self._reply(activity)

    @extend_schema(request=RsvpRequestSerializer, responses={200: ClubActivitySerializer})
    @action(detail=True, methods=["post"])
    def rsvp(self, request, *args, **kwargs):
        """Answer going, maybe or not going. Going beyond the capacity puts you on the waiting list."""
        activity = self.get_object()
        body = RsvpRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        service.answer(activity, request.user, body.validated_data["answer"])
        return self._reply(activity)

    @extend_schema(responses={200: AttendeeSerializer(many=True)})
    @action(detail=True)
    def attendees(self, request, *args, **kwargs):
        """Who is going or might, by display name, for the activity's audience and its staff."""
        activity = self.get_object()
        if not (
            service.is_staff(request.user, activity.organization)
            or service.in_audience(request.user, activity)
        ):
            raise PermissionDenied("Only the activity's audience sees who is going.")
        answers = (
            activity.rsvps.exclude(answer=Rsvp.Answer.NOT_GOING)
            .select_related("user")
            .order_by("waitlisted", "answer", "user__display_name")
        )
        return Response(AttendeeSerializer(answers, many=True).data)

    @extend_schema(
        responses=inline_serializer(
            "ActivityInvitees", {"invitee_ids": serializers.ListField(child=serializers.UUIDField())}
        )
    )
    @action(detail=True, url_path="invitees")
    def invitee_list(self, request, *args, **kwargs):
        """Who a selected-members activity is for, for its staff only."""
        organization = self._staff()
        activity = get_object_or_404(Activity, pk=kwargs["pk"], organization=organization)
        return Response({"invitee_ids": [str(pk) for pk in activity.invitees.values_list("pk", flat=True)]})


class ScheduleView(APIView):
    """The club schedule for its members: activities, tournaments and training sessions in date order."""

    permission_classes = [IsAuthenticated]

    def _items(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_membership(request.user, organization)
        kinds = [
            k for k in request.query_params.getlist("kind") if k in ("activity", "tournament", "training")
        ]
        when = "past" if request.query_params.get("when") == "past" else "upcoming"
        return organization, service.schedule(request.user, organization, when=when, kinds=kinds or None)

    @extend_schema(
        parameters=[
            WHEN,
            OpenApiParameter("kind", str, many=True, enum=["activity", "tournament", "training"]),
        ],
        responses={200: ScheduleItemSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        _, items = self._items(request, organization_pk)
        return Response(ScheduleItemSerializer(items, many=True).data)


class ScheduleCalendarView(ScheduleView):
    """The same schedule as an .ics file, to add to a phone's calendar."""

    @extend_schema(
        parameters=[
            WHEN,
            OpenApiParameter("kind", str, many=True, enum=["activity", "tournament", "training"]),
        ],
        responses={(200, "text/calendar"): OpenApiTypes.STR},
    )
    def get(self, request, organization_pk):
        organization, items = self._items(request, organization_pk)
        response = HttpResponse(service.ics(organization, items), content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="club-schedule.ics"'
        return response
