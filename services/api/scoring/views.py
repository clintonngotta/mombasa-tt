import uuid

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from competitions import matchday
from competitions.models import DrawVersion, Event, Match, Rubber, Tournament
from competitions.serializers import MatchDetailSerializer
from competitions.views import match_reply, require_staff, sees_draft, staff_tournament
from core.exceptions import ApiException
from core.pagination import StandardPagination
from core.permissions import PublicReads
from core.throttling import LiveReadThrottle
from organizations.access import membership_permissions
from organizations.models import Membership

from . import live, service
from .models import Scorecard, ScoreConflict
from .serializers import (
    AssignUmpireSerializer,
    ConfirmSerializer,
    ConflictReceiptSerializer,
    ConflictReportSerializer,
    LiveMatchSerializer,
    MyScorecardSerializer,
    ResolveConflictSerializer,
    ScorecardSerializer,
    ScoringOverviewSerializer,
    SubmitEventsSerializer,
    SubmitResultSerializer,
    TakeDeviceSerializer,
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


def device_of(request):
    """The caller's device, from the X-Device-Id header; None when it sends none or nonsense."""
    try:
        return uuid.UUID(request.headers.get("X-Device-Id", ""))
    except ValueError:
        return None


class ScoringOverviewViewSet(viewsets.GenericViewSet):
    """Scoring in one tournament as its competition staff see it (REQ-013): which matches are being
    scored or wait for their umpire's confirmation, who held each sheet on which device, and what
    devices wrote that the server did not accept."""

    permission_classes = [IsAuthenticated]
    serializer_class = ScoringOverviewSerializer

    def retrieve(self, request, tournament_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
        return Response(ScoringOverviewSerializer(self._overview(tournament)).data)

    @staticmethod
    def _overview(tournament: Tournament) -> dict:
        from reservations import service as reservations  # reservations builds on scoring's models

        held = [reservations.describe(reservation) for reservation in reservations.active_for(tournament)]
        return {**service.overview(tournament), "reservations": held}

    @extend_schema(request=ResolveConflictSerializer, responses={200: ScoringOverviewSerializer})
    def resolve(self, request, tournament_pk, pk):
        """Record what was done about a device's unaccepted events. The report stays on record."""
        serializer = ResolveConflictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            conflict = get_object_or_404(
                ScoreConflict.objects.select_for_update(of=("self",)).filter(
                    Q(scorecard__match__draw__event__tournament=tournament)
                    | Q(scorecard__rubber__match__draw__event__tournament=tournament)
                ),
                pk=pk,
            )
            service.resolve_conflict(conflict, request.user, serializer.validated_data["note"])
        return Response(ScoringOverviewSerializer(self._overview(tournament)).data)


class UmpireViewSet(viewsets.GenericViewSet):
    """Who scores which match (REQ-012): for the host's competition staff."""

    permission_classes = [IsAuthenticated]
    serializer_class = UmpireSerializer

    @extend_schema(responses={200: UmpireSerializer(many=True)})
    def list(self, request, tournament_pk, event_pk):
        """The host's members who can be given a match to score: those whose role lets them score, and
        those who run competitions or results."""
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
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
            where = f" (rubber {rubber.position})" if rubber else ""
            matchday.log(
                tournament,
                matchday.Action.UMPIRE_ASSIGNED if umpire else matchday.Action.UMPIRE_REMOVED,
                f"{matchday.match_title(match)}{where}" + (f": {umpire.display_name}" if umpire else ""),
                actor=request.user,
                match=match,
                table=match.table,
            )
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
                Q(
                    match__draw__event__tournament__status__in=running,
                    match__draw__status=DrawVersion.Status.PUBLISHED,
                    match__status=Match.Status.SCHEDULED,
                )
                | Q(
                    rubber__match__draw__event__tournament__status__in=running,
                    rubber__match__draw__status=DrawVersion.Status.PUBLISHED,
                    rubber__status=Rubber.Status.SCHEDULED,
                )
            )
            .order_by("assigned_at", "id")
        )
        page = [card for card in self.paginate_queryset(mine) if service.is_umpire_of(card, request.user)]
        return self.get_paginated_response(MyScorecardSerializer(page, many=True).data)

    def _shown(self, scorecard: Scorecard) -> Response:
        return Response(
            ScorecardSerializer(
                scorecard, context={"device_id": device_of(self.request), "request": self.request}
            ).data
        )

    def _reply(self, scorecard: Scorecard) -> Response:
        return self._shown(scorecards().prefetch_related("events").get(pk=scorecard.pk))

    def retrieve(self, request, pk):
        return self._shown(self._mine(scorecards().prefetch_related("events"), pk))

    @extend_schema(request=TakeDeviceSerializer, responses={200: ScorecardSerializer})
    def device(self, request, pk):
        """This device takes the sheet, so that one device scores a match at a time. A sheet held by
        another device is refused (`other_device`) unless `take_over` is set; taking over issues a new
        assignment id, which cuts the other device off."""
        serializer = TakeDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            scorecard = service.locked(pk, request.user)
            service.take_device(
                scorecard, request.user, asked["device_id"], asked["label"], asked["take_over"]
            )
        fresh = scorecards().prefetch_related("events").get(pk=scorecard.pk)
        return Response(
            ScorecardSerializer(fresh, context={"device_id": asked["device_id"], "request": request}).data
        )

    @extend_schema(request=ConflictReportSerializer, responses={201: ConflictReceiptSerializer})
    def conflicts(self, request, pk):
        """Tell the organizers what this device wrote that the server didn't accept. Open to whoever
        holds the sheet or held it before. It changes nothing about the score."""
        serializer = ConflictReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scorecard = Scorecard.objects.select_for_update(of=("self",)).filter(pk=pk).first()
            if scorecard is None or not service.may_report(scorecard, request.user):
                raise Http404
            kept = service.report_conflict(scorecard, request.user, serializer.validated_data)
        return Response(ConflictReceiptSerializer(kept).data, status=201)

    def _mine(self, found, pk) -> Scorecard:
        scorecard = get_object_or_404(found, pk=pk, umpire=self.request.user)
        if not service.is_umpire_of(scorecard, self.request.user):
            raise Http404
        return scorecard

    @extend_schema(request=SubmitEventsSerializer, responses={200: SubmitResultSerializer})
    def events(self, request, pk):
        """Send score events in order. Each is replayed through the server's own scoring rules. Only the
        sheet is locked, not the tournament: points arrive from every table at once and change nothing
        outside their own sheet until it is confirmed. A retry
        of an accepted event is skipped; the first event out of sequence or against the rules stops the
        batch and is reported in `refused`, with everything before it kept."""
        serializer = SubmitEventsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            scorecard = service.locked(pk, request.user)
            outcome = service.submit(
                scorecard, request.user, asked["assignment_id"], asked["events"], device_of(request)
            )
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
            found = self._mine(scorecards(), pk)
            # Like every change to a tournament: its row first, then the sheet.
            Tournament.objects.select_for_update(of=("self",)).get(pk=service.event_of(found).tournament_id)
            scorecard = service.locked(pk, request.user)
            asked = serializer.validated_data
            service.confirm(
                scorecard, request.user, asked["assignment_id"], asked["revision"], device_of(request)
            )
        return self._reply(scorecard)


class LiveViewSet(viewsets.GenericViewSet):
    """GET /tournaments/{id}/live/: the matches being scored now, for anybody who may see the
    tournament (published, or a draft its organizers and approvers see). Pages fetch it again when the
    tournament's socket says a score changed, and on a timer when the socket is down (TASK-084)."""

    permission_classes = [PublicReads]
    public_actions = ("list",)
    throttle_classes = [LiveReadThrottle]
    pagination_class = None

    @extend_schema(responses=LiveMatchSerializer(many=True))
    def list(self, request, tournament_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        if tournament.status == Tournament.Status.DRAFT and not sees_draft(request.user, tournament):
            raise Http404
        return Response(LiveMatchSerializer(live.live_matches(tournament), many=True).data)
