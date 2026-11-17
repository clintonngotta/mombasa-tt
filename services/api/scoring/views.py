from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from competitions.models import DrawVersion, Event, Match, Rubber, Tournament
from competitions.serializers import MatchDetailSerializer
from competitions.views import match_reply, staff_tournament
from core.exceptions import ApiException
from core.pagination import StandardPagination
from organizations.access import membership_permissions
from organizations.models import Membership

from . import service
from .models import Scorecard
from .serializers import (
    AssignUmpireSerializer,
    ConfirmSerializer,
    MyScorecardSerializer,
    ScorecardSerializer,
    SubmitEventsSerializer,
    SubmitResultSerializer,
    UmpireSerializer,
)


def scorecards():
    return Scorecard.objects.select_related(
        "match__draw__event__tournament",
        "match__entry_a",
        "match__entry_b",
        "match__table",
        "rubber__match__draw__event__tournament",
        "rubber__match__entry_a",
        "rubber__match__entry_b",
        "rubber__match__table",
    )


class UmpireViewSet(viewsets.GenericViewSet):
    """Who scores which match (REQ-012): for the host's competition staff."""

    permission_classes = [IsAuthenticated]
    serializer_class = UmpireSerializer

    @extend_schema(responses={200: UmpireSerializer(many=True)})
    def list(self, request, tournament_pk, event_pk):
        """The host's members who can be given a match to score: those whose role lets them score, and
        those who run competitions or results."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
        get_object_or_404(Event, pk=event_pk, tournament=tournament)
        members = (
            Membership.objects.active()
            .filter(organization=tournament.organization)
            .select_related("user", "organization")
            .prefetch_related("roles", "organization__roles")
            .order_by("user__display_name")
        )
        able = [m.user for m in members if membership_permissions(m) & service.UMPIRE_PERMISSIONS]
        return Response(UmpireSerializer(able, many=True).data)

    @extend_schema(request=AssignUmpireSerializer, responses={200: MatchDetailSerializer})
    def assign(self, request, tournament_pk, event_pk, pk):
        """Give a match, or one rubber of a tie, to an umpire; `user_id` null takes it back. A new
        assignment cuts off the device that held the old one. Points already scored stay."""
        serializer = AssignUmpireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            match = get_object_or_404(
                Match.objects.select_related("draw__event__tournament__organization", "entry_a", "entry_b"),
                pk=pk,
                draw__event_id=event_pk,
                draw__event__tournament=tournament,
                draw__status=DrawVersion.Status.PUBLISHED,
            )
            rubber = None
            if asked.get("rubber_id"):
                rubber = get_object_or_404(Rubber, pk=asked["rubber_id"], match=match)
            umpire = None
            if asked["user_id"]:
                umpire = User.objects.filter(pk=asked["user_id"], is_active=True).first()
                if umpire is None:
                    raise ApiException("not_an_umpire", "We don't know that person.", 409)
            service.assign(match, rubber, umpire, request.user)
        return match_reply(request, match.draw, match.id)


class ScorecardViewSet(viewsets.GenericViewSet):
    """The assigned umpire's sheets (REQ-012). A sheet exists only for the umpire assigned to it; a
    reassigned umpire loses it at once."""

    permission_classes = [IsAuthenticated]
    serializer_class = ScorecardSerializer
    pagination_class = StandardPagination

    @extend_schema(responses={200: MyScorecardSerializer(many=True)})
    def list(self, request):
        """Matches the caller is assigned to score and hasn't confirmed, in tournaments still running."""
        running = [Tournament.Status.PUBLISHED, Tournament.Status.IN_PROGRESS]
        mine = (
            scorecards()
            .filter(umpire=request.user, confirmed_at__isnull=True)
            .filter(
                Q(match__draw__event__tournament__status__in=running, match__status=Match.Status.SCHEDULED)
                | Q(
                    rubber__match__draw__event__tournament__status__in=running,
                    rubber__status=Rubber.Status.SCHEDULED,
                )
            )
            .order_by("assigned_at", "id")
        )
        page = self.paginate_queryset(mine)
        return self.get_paginated_response(MyScorecardSerializer(page, many=True).data)

    def _reply(self, scorecard: Scorecard) -> Response:
        fresh = scorecards().prefetch_related("events").get(pk=scorecard.pk)
        return Response(ScorecardSerializer(fresh).data)

    def retrieve(self, request, pk):
        scorecard = get_object_or_404(scorecards().prefetch_related("events"), pk=pk, umpire=request.user)
        return Response(ScorecardSerializer(scorecard).data)

    @extend_schema(request=SubmitEventsSerializer, responses={200: SubmitResultSerializer})
    def events(self, request, pk):
        """Send score events in order. Each is replayed through the server's own scoring rules. A retry
        of an accepted event is skipped; the first event out of sequence or against the rules stops the
        batch and is reported in `refused`, with everything before it kept."""
        serializer = SubmitEventsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            scorecard = service.locked(pk, request.user)
            outcome = service.submit(scorecard, request.user, asked["assignment_id"], asked["events"])
        return Response(
            SubmitResultSerializer(
                {
                    **outcome,
                    "revision": scorecard.revision,
                    "status": scorecard.shown_status,
                    "state": scorecard.state,
                }
            ).data
        )

    @extend_schema(request=ConfirmSerializer, responses={200: ScorecardSerializer})
    def confirm(self, request, pk):
        """The umpire confirms the result, which makes it official: the winner moves on through the
        draw. Refused (`match_not_finished`) unless the accepted events are a finished match."""
        serializer = ConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            found = get_object_or_404(scorecards(), pk=pk, umpire=request.user)
            # Like every change to a tournament: its row first, then the sheet.
            Tournament.objects.select_for_update(of=("self",)).get(pk=service.event_of(found).tournament_id)
            scorecard = service.locked(pk, request.user)
            service.confirm(scorecard, request.user, serializer.validated_data["revision"])
        return self._reply(scorecard)
