"""The inbox, preferences and announcements (REQ-019, TASK-033)."""

import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from competitions.models import EntryPlayer, Event
from core.pagination import StandardPagination
from organizations.access import require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from . import service
from .models import ALWAYS_ON, Category, Notification, Preference
from .serializers import (
    AnnouncementSerializer,
    NotificationSerializer,
    PreferencesSerializer,
    SentSerializer,
    UnreadSerializer,
)


class InboxViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The signed-in player's alerts, newest first."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        mine = Notification.objects.filter(recipient=self.request.user)
        if self.action == "list" and self.request.query_params.get("unread") in ("true", "1"):
            mine = mine.filter(read_at__isnull=True)
        return mine

    @extend_schema(parameters=[OpenApiParameter("unread", bool, description="Only unread alerts")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses={200: UnreadSerializer})
    @action(detail=False, url_path="unread-count")
    def unread_count(self, request):
        count = Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()
        return Response(UnreadSerializer({"unread": count}).data)

    @extend_schema(request=None, responses={200: NotificationSerializer})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        alert = self.get_object()
        if alert.read_at is None:
            alert.read_at = timezone.now()
            alert.save(update_fields=["read_at"])
        return Response(self.get_serializer(alert).data)

    @extend_schema(request=None, responses={200: UnreadSerializer})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return Response(UnreadSerializer({"unread": 0}).data)


class PreferencesView(APIView):
    """Which categories of alerts the player gets. Being called to a table can't be switched off."""

    permission_classes = [IsAuthenticated]

    def _reply(self, user):
        off = set(Preference.objects.filter(user=user).values_list("category", flat=True))
        rows = [
            {"category": value, "label": label, "enabled": value not in off, "locked": value in ALWAYS_ON}
            for value, label in Category.choices
        ]
        return Response(PreferencesSerializer({"preferences": rows}).data)

    @extend_schema(responses={200: PreferencesSerializer})
    def get(self, request):
        return self._reply(request.user)

    @extend_schema(request=PreferencesSerializer, responses={200: PreferencesSerializer})
    @transaction.atomic
    def put(self, request):
        body = PreferencesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        for row in body.validated_data["preferences"]:
            if row["enabled"] or row["category"] in ALWAYS_ON:
                Preference.objects.filter(user=request.user, category=row["category"]).delete()
            else:
                Preference.objects.get_or_create(user=request.user, category=row["category"])
        return self._reply(request.user)


class AnnouncementView(APIView):
    """Send an announcement to an explicit audience: the organization's members, the players of one of
    its events, or named members. Needs announcements.manage."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=AnnouncementSerializer, responses={200: SentSerializer})
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.ANNOUNCEMENTS_MANAGE)
        body = AnnouncementSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        members = Membership.objects.active().filter(organization=organization)
        if data["audience"] == "members":
            recipients = set(members.values_list("user_id", flat=True))
        elif data["audience"] == "event":
            event = get_object_or_404(Event, pk=data["event_id"], tournament__organization=organization)
            recipients = set(EntryPlayer.objects.filter(entry__event=event).values_list("user_id", flat=True))
        else:
            recipients = set(members.filter(user_id__in=data["user_ids"]).values_list("user_id", flat=True))
            if recipients != set(data["user_ids"]):
                raise ValidationError({"user_ids": "Choose members of the organization."})
        sent = service.notify(
            recipients,
            Category.ANNOUNCEMENT,
            data["title"],
            body=data.get("body", ""),
            subject=f"announcement:{uuid.uuid4()}",
            organization=organization,
            link="/club",
        )
        return Response(SentSerializer({"sent": sent}).data)
