from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.permissions import Permission

from . import corrections, drawing, matchday, official, recap
from .models import DrawVersion, Entry, Match, Resolution, Rubber, Tournament
from .serializers import (
    MatchDetailSerializer,
    ResolutionSerializer,
    ResolveSerializer,
    ResultCorrectionSerializer,
    ResultEntrySerializer,
)
from .views import match_reply, require_staff, staff_tournament


def describe_resolution(resolution: Resolution) -> dict:
    """A resolution as ResolutionSerializer shows it."""
    match = resolution.match
    shown = drawing.describe_match(match.draw, match.id) or {}
    progress = (
        "decided"
        if match.status == Match.Status.COMPLETED
        else "on_table"
        if match.dispatched_at
        else "being_scored"
        if corrections.started(match)
        else "not_started"
    )
    return {
        "id": resolution.id,
        "event_id": resolution.event_id,
        "event_name": resolution.event.name,
        "match_id": match.id,
        "label": " · ".join(part for part in (shown.get("group_name"), shown.get("round_name")) if part),
        "a": official.title(match.entry_a),
        "b": official.title(match.entry_b),
        "side": resolution.side,
        "old_entry": official.title(resolution.old_entry),
        "new_entry": official.title(resolution.new_entry),
        "progress": progress,
        "reason": resolution.cause.reason,
        "corrected_by": resolution.cause.recorded_by.display_name if resolution.cause.recorded_by else "",
        "created_at": resolution.created_at,
        "choice": resolution.choice,
        "note": resolution.note,
        "resolved_by": resolution.resolved_by.display_name if resolution.resolved_by else "",
        "resolved_at": resolution.resolved_at,
    }


def resolutions_of(tournament: Tournament) -> list[dict]:
    """The tournament's resolutions, those still waiting first."""
    found = Resolution.objects.filter(event__tournament=tournament).select_related(
        "event", "match__draw__event", "match__entry_a", "match__entry_b", "old_entry", "new_entry",
        "cause__recorded_by", "resolved_by",
    )  # fmt: skip
    ordered = sorted(found, key=lambda r: (r.resolved_at is not None, r.created_at))
    return [describe_resolution(resolution) for resolution in ordered]


def results_tournament(user, pk) -> tuple[Tournament, bool]:
    """The tournament, locked, for whoever may enter its results: its competition staff, or its host's
    referee (decision D5), who needs no other role. Also says whether the caller is a referee."""
    tournament = get_object_or_404(
        Tournament.objects.select_for_update(of=("self",)).select_related("organization"), pk=pk
    )
    referee = Permission.RESULTS_REFEREE in effective_permissions(user, tournament.organization)
    if not referee:
        require_staff(user, tournament)
    return tournament, referee


REFEREE_ONLY = (Match.Outcome.WALKOVER, Match.Outcome.DISQUALIFIED)


def require_referee_for(referee: bool, match: Match, rubber: Rubber | None, outcome: str) -> None:
    """Only the referee awards walkovers and disqualifications (decision D5, REQ-043): giving a match
    either, or taking one away, needs `results.referee`."""
    standing = official.current(match, rubber)
    touches = outcome in REFEREE_ONLY or (standing is not None and standing.outcome in REFEREE_ONLY)
    if touches and not referee:
        raise ApiException(
            "referee_only", "Only the referee awards or changes a walkover or a disqualification.", 403
        )


class ResultViewSet(viewsets.GenericViewSet):
    """Results the organizers enter or correct, and what a correction leaves to decide (REQ-015)."""

    permission_classes = [IsAuthenticated]
    serializer_class = ResultEntrySerializer

    def _target(self, tournament: Tournament, event_pk, pk, asked) -> tuple[Match, Rubber | None, Entry]:
        match = get_object_or_404(
            Match.objects.select_related("draw__event__tournament__organization", "entry_a", "entry_b"),
            pk=pk,
            draw__event_id=event_pk,
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
        )
        rubber = None
        if asked["rubber_id"]:
            rubber = match.rubbers.filter(pk=asked["rubber_id"]).first()
            if rubber is None:
                raise ApiException("not_in_match", "That rubber isn't part of this tie.", 409)
        winner = next(
            (e for e in (match.entry_a, match.entry_b) if e and e.id == asked["winner_entry_id"]), None
        )
        if winner is None:
            raise ApiException("not_in_match", "The winner is one of the two sides of the match.", 409)
        return match, rubber, winner

    @extend_schema(request=ResultEntrySerializer, responses={200: MatchDetailSerializer})
    def enter(self, request, tournament_pk, event_pk, pk):
        """Competition staff record a result themselves: a walkover, a retirement, or a match scored
        on paper. It is official at once: the winner moves on and the table and players are freed.
        A match that already has a result is changed with `correct`."""
        serializer = ResultEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament, referee = results_tournament(request.user, tournament_pk)
            match, rubber, winner = self._target(tournament, event_pk, pk, asked)
            require_referee_for(referee, match, rubber, asked["outcome"])
            table = match.table  # read before the result frees it
            corrections.enter(
                match, rubber, winner, asked["outcome"], asked["games"], request.user, asked["reason"]
            )
            matchday.log(
                tournament,
                matchday.Action.RESULT_ENTERED,
                matchday.result_summary(match, rubber, winner, asked["outcome"], asked["games"]),
                actor=request.user,
                match=match,
                table=table,
                reason=asked["reason"],
            )
        return match_reply(request, match.draw, match.id)

    @extend_schema(request=ResultCorrectionSerializer, responses={200: MatchDetailSerializer})
    def correct(self, request, tournament_pk, event_pk, pk):
        """Replace the official result of a decided match or rubber, with a reason. The earlier result
        is kept. If the winner changes and the match they went on to has not started, the right entry
        takes that place; if it has started, the event is paused and the organizers decide
        (`corrections`)."""
        serializer = ResultCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament, referee = results_tournament(request.user, tournament_pk)
            match, rubber, winner = self._target(tournament, event_pk, pk, asked)
            require_referee_for(referee, match, rubber, asked["outcome"])
            corrections.correct(
                match, rubber, winner, asked["outcome"], asked["games"], request.user, asked["reason"]
            )
            matchday.log(
                tournament,
                matchday.Action.RESULT_CORRECTED,
                matchday.result_summary(match, rubber, winner, asked["outcome"], asked["games"]),
                actor=request.user,
                match=match,
                reason=asked["reason"],
            )
        return match_reply(request, match.draw, match.id)

    @extend_schema(responses={200: ResolutionSerializer(many=True)})
    def resolutions(self, request, tournament_pk):
        """Later matches put in question by corrected results: those waiting for a decision first,
        then those decided."""
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
        return Response(ResolutionSerializer(resolutions_of(tournament), many=True).data)

    @extend_schema(request=ResolveSerializer, responses={200: ResolutionSerializer(many=True)})
    def resolve(self, request, tournament_pk, pk):
        """Decide one: `keep` the later match as it was played, or `replace` the entry, which strikes
        out what was played there so it can be played again. The event carries on when none is left."""
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            resolution = get_object_or_404(
                Resolution.objects.select_related("event", "match__draw__event__tournament", "cause"),
                pk=pk,
                event__tournament=tournament,
            )
            match = resolution.match
            if asked["choice"] == Resolution.Choice.REPLACE:
                # Replacing strikes out what was recorded there, a walkover or disqualification included.
                referee = Permission.RESULTS_REFEREE in effective_permissions(
                    request.user, tournament.organization
                )
                standing = [official.current(match, rubber) for rubber in [None, *match.rubbers.all()]]
                if not referee and any(r is not None and r.outcome in REFEREE_ONLY for r in standing):
                    raise ApiException(
                        "referee_only",
                        "This match holds a walkover or a disqualification: only the referee strikes it out.",
                        403,
                    )
            corrections.resolve(resolution, asked["choice"], asked["note"], request.user)
            matchday.log(
                tournament,
                matchday.Action.CORRECTION_SETTLED,
                f"{matchday.match_title(match)}: "
                + ("kept as played" if asked["choice"] == Resolution.Choice.KEEP else "entry replaced"),
                actor=request.user,
                match=match,
                reason=asked["note"],
            )
        return Response(ResolutionSerializer(resolutions_of(tournament), many=True).data)


class RecapSideChangeSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    before = serializers.IntegerField()
    after = serializers.IntegerField()
    delta = serializers.IntegerField()


class RecapPlayerSerializer(serializers.Serializer):
    side = serializers.CharField()
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()


class RecapSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    tournament_id = serializers.UUIDField()
    tournament_name = serializers.CharField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    side_a = serializers.CharField()
    side_b = serializers.CharField()
    official = serializers.BooleanField()
    outcome = serializers.CharField()
    winner_side = serializers.CharField(allow_null=True)
    games = serializers.ListField(child=serializers.ListField(child=serializers.IntegerField()))
    players = RecapPlayerSerializer(many=True)
    rating = serializers.ChoiceField(
        choices=["none", "processing", "done", "unrated"],
        help_text="processing: the official result waits for the rating worker; no number is shown yet.",
    )
    rating_changes = RecapSideChangeSerializer(many=True)


class MatchRecapView(APIView):
    """A match's recap for sharing (REQ-018): public for a published tournament, signed in or not."""

    permission_classes = [AllowAny]
    public_actions = ("get",)  # throttled for signed-out callers (core/throttling.py)

    @extend_schema(responses={200: RecapSerializer})
    def get(self, request, tournament_pk, event_pk, pk):
        match = recap.published_match(tournament_pk, event_pk, pk)
        if match is None:
            raise Http404
        return Response(RecapSerializer(recap.recap(match)).data)


class MatchCardView(APIView):
    """The recap as a branded square image (SVG) to download or share."""

    permission_classes = [AllowAny]
    public_actions = ("get",)  # throttled for signed-out callers (core/throttling.py)

    @extend_schema(responses={(200, "image/svg+xml"): OpenApiTypes.STR})
    def get(self, request, tournament_pk, event_pk, pk):
        match = recap.published_match(tournament_pk, event_pk, pk)
        if match is None:
            raise Http404
        response = HttpResponse(recap.card_svg(recap.recap(match)), content_type="image/svg+xml")
        response["Content-Disposition"] = 'inline; filename="coast-tt-result.svg"'
        response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
        return response
