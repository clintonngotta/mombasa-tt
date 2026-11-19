"""Club sessions (REQ-027, TASK-044): staff schedule, invite and take attendance; members answer."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from core.pagination import StandardPagination
from organizations.access import require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import club_sessions
from .club_session_serializers import (
    AttendanceSerializer,
    ClubSessionSerializer,
    InviteSerializer,
    MySessionInvitationSerializer,
    SessionInvitationSerializer,
)
from .models import ClubSession, SessionInvitation

TRAINING = Permission.TRAINING_MANAGE
ACCEPTED = Q(invitations__status=SessionInvitation.Status.ACCEPTED)


def with_counts(queryset):
    return queryset.annotate(
        invited=Count("invitations", distinct=True),
        accepted=Count("invitations", filter=ACCEPTED, distinct=True),
    ).prefetch_related("tables__venue")


class ClubSessionViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """The club's training sessions, for its training staff."""

    serializer_class = ClubSessionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def organization(self) -> Organization:
        if not hasattr(self, "_organization"):
            self._organization = get_object_or_404(Organization, pk=self.kwargs["organization_pk"])
            require_permission(self.request.user, self._organization, TRAINING)
        return self._organization

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False):
            context["organization"] = self.organization()
        return context

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ClubSession.objects.none()
        sessions = with_counts(ClubSession.objects.filter(organization=self.organization()))
        if self.action == "list":
            now = timezone.now()
            if self.request.query_params.get("when") == "past":
                return sessions.filter(ends_at__lte=now).order_by("-starts_at", "id")
            return sessions.filter(ends_at__gt=now)
        return sessions

    def _fresh(self, session):
        return self.get_serializer(with_counts(ClubSession.objects.filter(pk=session.pk)).get()).data

    @extend_schema(parameters=[OpenApiParameter("when", str, enum=["upcoming", "past"])])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tables = data.pop("tables")
        club_sessions.ensure_tables_free(tables, data["starts_at"], data["ends_at"])
        session = ClubSession.objects.create(
            organization=self.organization(), created_by=request.user, **data
        )
        session.tables.set(tables)
        return Response(self._fresh(session), status=status.HTTP_201_CREATED)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        session = ClubSession.objects.select_for_update().get(pk=self.get_object().pk)
        if session.status != ClubSession.Status.SCHEDULED:
            raise ApiException("session_cancelled", "This session was cancelled.", 409)
        serializer = self.get_serializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tables = data.pop("tables", None)
        moving = tables is not None or any(
            key in data and data[key] != getattr(session, key) for key in ("starts_at", "ends_at")
        )
        if moving:
            if club_sessions.accepted_count(session):
                raise ApiException(
                    "session_has_members",
                    "Members have accepted this session: cancel it and schedule a new one to move it.",
                    409,
                )
            club_sessions.ensure_tables_free(
                tables if tables is not None else list(session.tables.all()),
                data.get("starts_at", session.starts_at),
                data.get("ends_at", session.ends_at),
                exclude=session,
            )
        if "capacity" in data and data["capacity"] is not None:
            if data["capacity"] < club_sessions.accepted_count(session):
                raise ApiException(
                    "capacity_below_accepted", "More members have already accepted than that.", 409
                )
        for key, value in data.items():
            setattr(session, key, value)
        session.save()
        if tables is not None:
            session.tables.set(tables)
        return Response(self._fresh(session))

    @extend_schema(request=None, responses={200: ClubSessionSerializer})
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, *args, **kwargs):
        """Cancel the session: its tables and every accepted member's time are free again."""
        session = ClubSession.objects.select_for_update().get(pk=self.get_object().pk)
        if session.status != ClubSession.Status.CANCELLED:
            session.status = ClubSession.Status.CANCELLED
            session.cancelled_at = timezone.now()
            session.save(update_fields=["status", "cancelled_at"])
        return Response(self._fresh(session))


class SessionInvitationViewSet(viewsets.GenericViewSet):
    """Who is invited to a club session, their answers, and attendance; for the club's training staff."""

    serializer_class = SessionInvitationSerializer
    permission_classes = [IsAuthenticated]

    def session(self) -> ClubSession:
        organization = get_object_or_404(Organization, pk=self.kwargs["organization_pk"])
        require_permission(self.request.user, organization, TRAINING)
        return get_object_or_404(organization.club_sessions, pk=self.kwargs["session_pk"])

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SessionInvitation.objects.none()
        return self.session().invitations.select_related("user").order_by("user__display_name", "id")

    @extend_schema(responses={200: SessionInvitationSerializer(many=True)})
    def list(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @extend_schema(request=InviteSerializer, responses={200: SessionInvitationSerializer(many=True)})
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Invite active members. Members already invited keep their invitation and answer."""
        session = self.session()
        if session.status != ClubSession.Status.SCHEDULED or session.ends_at <= timezone.now():
            raise ApiException("session_closed", "This session is cancelled or over.", 409)
        body = InviteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        wanted = set(body.validated_data["user_ids"])
        members = set(
            Membership.objects.active()
            .filter(organization=session.organization, user__in=wanted)
            .values_list("user_id", flat=True)
        )
        if wanted - members:
            raise ApiException("not_members", "Only active members of the club can be invited.", 400)
        users = get_user_model().objects.filter(pk__in=members)
        SessionInvitation.objects.bulk_create(
            [SessionInvitation(session=session, user=user, invited_by=request.user) for user in users],
            ignore_conflicts=True,
        )
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @extend_schema(request=AttendanceSerializer, responses={200: SessionInvitationSerializer})
    def partial_update(self, request, *args, **kwargs):
        """Mark whether the member came. Marking again with the same answer changes nothing."""
        invitation = get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])
        body = AttendanceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        invitation = club_sessions.record_attendance(
            invitation, body.validated_data["attended"], request.user
        )
        return Response(self.get_serializer(invitation).data)


class MySessionInvitationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The signed-in member's invitations to club sessions, and their answers."""

    serializer_class = MySessionInvitationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SessionInvitation.objects.none()
        mine = SessionInvitation.objects.filter(user=self.request.user).select_related(
            "session__organization"
        )
        if self.action == "list":
            if self.request.query_params.get("when") == "past":
                mine = mine.filter(session__ends_at__lte=timezone.now()).order_by("-session__starts_at")
            else:
                mine = mine.filter(session__ends_at__gt=timezone.now()).order_by("session__starts_at")
        return mine.prefetch_related("session__tables__venue")

    def _answer(self, invitation):
        session = with_counts(ClubSession.objects.filter(pk=invitation.session_id)).get()
        invitation.session = session
        return Response(self.get_serializer(invitation).data)

    @extend_schema(parameters=[OpenApiParameter("when", str, enum=["upcoming", "past"])])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses={200: MySessionInvitationSerializer})
    @action(detail=True, methods=["post"])
    def accept(self, request, *args, **kwargs):
        """Accept: holds this time in your calendar. Refused when you already have something on, the
        session is full or it was cancelled. Accepting again changes nothing."""
        return self._answer(club_sessions.accept(self.get_object()))

    @extend_schema(request=None, responses={200: MySessionInvitationSerializer})
    @action(detail=True, methods=["post"])
    def decline(self, request, *args, **kwargs):
        """Decline, or withdraw an acceptance: your time is free again."""
        return self._answer(club_sessions.decline(self.get_object()))
