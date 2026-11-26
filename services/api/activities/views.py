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
from organizations.access import effective_permissions, require_membership, require_permission
from organizations.committee import local_today
from organizations.models import Membership, Organization
from organizations.permissions import Permission
from organizations.representatives import senders_of
from profiles.models import listed_profiles

from . import costs, service
from .models import Activity, Rsvp
from .serializers import (
    AttendeeSerializer,
    CancelActivitySerializer,
    ClubActivitySerializer,
    MarkAttendanceSerializer,
    RsvpRequestSerializer,
    ScheduleItemSerializer,
    ShareCostSerializer,
)

WHEN = OpenApiParameter("when", str, enum=["upcoming", "past"])
A = Activity.Audience
MAX_EVENTS = 100


def audience_context(user, organization: Organization | None = None) -> dict:
    """What the serializer needs to tell whether an activity is for the user, found once for a list: the
    organizations they belong to, the activities that name them, and whom they represent where."""
    memberships = Membership.objects.active().filter(user=user)
    named = Activity.invitees.through.objects.filter(user_id=user.pk)
    if organization is not None:
        memberships = memberships.filter(organization=organization)
        named = named.filter(activity__organization=organization)
    represents: dict = {}
    for body_id, sender_id in service.seats(user, organization).values_list("body_id", "sender_id"):
        represents.setdefault(body_id, set()).add(sender_id)
    return {
        "member_of": set(memberships.values_list("organization_id", flat=True)),
        "invited": set(named.values_list("activity_id", flat=True)),
        "represents": represents,
    }


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
        activities = (
            service.visible(self.request.user, self.organization())
            .select_related("organization")
            .prefetch_related("rsvps", "clubs")
        )
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
        context.update(audience_context(self.request.user, organization))
        context["today"] = local_today(organization)
        context["finance_staff"] = bool(
            effective_permissions(self.request.user, organization)
            & {Permission.FINANCES_VIEW, Permission.FINANCES_MANAGE}
        )
        return context

    def _staff(self) -> Organization:
        organization = self.organization()
        require_permission(self.request.user, organization, service.MANAGE)
        return organization

    def _invitees(self, organization, ids, audience):
        """The people chosen: active members for selected members; for named people, members or
        players listed in the directory."""
        if ids is None:
            return None
        allowed = set(
            Membership.objects.active()
            .filter(organization=organization, user__in=ids)
            .values_list("user_id", flat=True)
        )
        if audience == A.NAMED:
            allowed |= set(listed_profiles().filter(user__in=ids).values_list("user_id", flat=True))
        if set(ids) - allowed:
            message = (
                "Name members or players listed in the directory."
                if audience == A.NAMED
                else "Only active members of the club can be invited."
            )
            raise ValidationError({"invitee_ids": message})
        return get_user_model().objects.filter(pk__in=allowed)

    def _clubs(self, organization, ids, audience):
        """Whose representatives are invited: only organizations that send theirs to this body."""
        if audience == A.REPRESENTATIVES and not organization.is_body:
            raise ValidationError({"audience": "Only a governing body invites representatives."})
        if ids is None:
            return None
        found = senders_of(organization).filter(pk__in=ids)
        if audience != A.REPRESENTATIVES or found.count() != len(set(ids)):
            raise ValidationError(
                {"club_ids": "Choose from the organizations that send you representatives."}
            )
        return found

    def _set_people(self, activity, invitees, clubs):
        if activity.audience not in (A.SELECTED, A.NAMED):
            activity.invitees.clear()
        elif invitees is not None:
            activity.invitees.set(invitees)
        if activity.audience != A.REPRESENTATIVES:
            activity.clubs.clear()
        elif clubs is not None:
            activity.clubs.set(clubs)

    def _reply(self, activity, code=status.HTTP_200_OK):
        fresh = (
            Activity.objects.select_related("organization")
            .prefetch_related("rsvps", "clubs")
            .get(pk=activity.pk)
        )
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
        club_ids = data.pop("club_ids", None)
        audience = data.get("audience", A.MEMBERS)
        clubs = self._clubs(organization, club_ids, audience)
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
        invitees = self._invitees(organization, invitee_ids, audience)
        activity = Activity.objects.create(organization=organization, created_by=request.user, **data)
        self._set_people(activity, invitees, clubs)
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
        club_ids = data.pop("club_ids", None)
        project_id = data.pop("welfare_project_id", activity.welfare_project_id)
        audience = data.get("audience", activity.audience)
        clubs = self._clubs(organization, club_ids, audience)
        if activity.campaign_id and audience not in service.MEMBER_AUDIENCES:
            raise ApiException("members_only", "Its cost is shared among members; keep it for members.", 409)
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
        invitees = self._invitees(organization, invitee_ids, audience)
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
        self._set_people(activity, invitees, clubs)
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

    @extend_schema(request=ShareCostSerializer, responses={200: ClubActivitySerializer})
    @action(detail=True, methods=["post"], url_path="cost-share")
    def cost_share(self, request, *args, **kwargs):
        """Share the cost among those going (REQ-039 Phase 2): a one-time due for each, through the
        ledger. Takes activities.manage and finances.manage, since it makes members owe."""
        organization = self._staff()
        require_permission(request.user, organization, Permission.FINANCES_MANAGE)
        activity = get_object_or_404(Activity, pk=kwargs["pk"], organization=organization)
        body = ShareCostSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        costs.share(activity, request.user, local_today(organization), **body.validated_data)
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
        """Who is going or might, by display name, for the activity's audience and its staff; for an
        event open to all players, for its staff only. Staff also see who checked in and attended."""
        activity = self.get_object()
        staff = service.is_staff(request.user, activity.organization)
        listed = activity.audience != A.OPEN and service.in_audience(request.user, activity)
        if not (staff or listed):
            raise PermissionDenied("Only the activity's audience sees who is going.")
        answers = (
            activity.rsvps.exclude(answer=Rsvp.Answer.NOT_GOING)
            .select_related("user")
            .order_by("waitlisted", "answer", "user__display_name")[:2000]
        )
        return Response(AttendeeSerializer(answers, many=True, context={"staff": staff}).data)

    @extend_schema(request=None, responses={200: ClubActivitySerializer})
    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, *args, **kwargs):
        """Say you are there, while it runs. If you hadn't answered you take a place when one is free."""
        activity = self.get_object()
        service.check_in(activity, request.user)
        return self._reply(activity)

    @extend_schema(request=MarkAttendanceSerializer, responses={200: AttendeeSerializer})
    @action(detail=True, methods=["post"])
    def attendance(self, request, *args, **kwargs):
        """Staff mark someone there or not, once it has started."""
        organization = self._staff()
        activity = get_object_or_404(Activity, pk=kwargs["pk"], organization=organization)
        body = MarkAttendanceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        rsvp = service.mark(
            activity,
            request.user,
            rsvp_id=data.get("rsvp"),
            user_id=data.get("user_id"),
            attended=data["attended"],
        )
        return Response(AttendeeSerializer(rsvp, context={"staff": True}).data)

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


class MyEventsView(APIView):
    """GET /me/events/: events that invite you beyond your clubs' own activities and haven't ended: you
    are named, you represent a club it is for, or it is open to all players. Soonest first."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ClubActivitySerializer(many=True)})
    def get(self, request):
        events = list(service.events_for(request.user)[:MAX_EVENTS])
        context = {"request": request, **audience_context(request.user)}
        return Response(ClubActivitySerializer(events, many=True, context=context).data)


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
