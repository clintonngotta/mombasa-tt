import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from competitions import matchday
from competitions.models import DrawVersion, Match, Tournament
from competitions.serializers import MatchDetailSerializer
from competitions.views import match_reply, require_staff, staff_tournament
from core.exceptions import ApiException
from facilities.models import Table

from . import board, control, service, umpires
from .models import TournamentUmpire
from .serializers import (
    AddUmpireSerializer,
    ArrivalSerializer,
    AutoDispatchSerializer,
    BlockSerializer,
    BoardSerializer,
    DeskEntrySerializer,
    DispatchSerializer,
    MatchDayLogSerializer,
    MoveSerializer,
    RecallSerializer,
    ReservationSerializer,
    TableStateSerializer,
    TableUmpireSerializer,
    UmpireCandidateSerializer,
    UmpireRosterSerializer,
)


class TournamentTables:
    """Finding the tournament for its competition staff, and its published matches."""

    def _tournament(self, request, tournament_pk) -> Tournament:
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
        return tournament

    def _match(self, tournament: Tournament, event_pk, pk) -> Match:
        return get_object_or_404(
            Match.objects.select_related("draw__event__tournament__organization", "entry_a", "entry_b"),
            pk=pk,
            draw__event_id=event_pk,
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
        )


class DispatchViewSet(TournamentTables, viewsets.GenericViewSet):
    """Tables and the matches on them (REQ-014), for the host's competition staff."""

    permission_classes = [IsAuthenticated]
    serializer_class = TableStateSerializer

    @extend_schema(responses={200: TableStateSerializer(many=True)})
    def tables(self, request, tournament_pk):
        """The tournament's tables in use and which are free. A table at a shared venue may be held by
        another tournament's match."""
        return Response(
            TableStateSerializer(service.tables_of(self._tournament(request, tournament_pk)), many=True).data
        )

    @extend_schema(responses={200: ReservationSerializer(many=True)})
    def reservations(self, request, tournament_pk):
        """Matches of this tournament that are on a table, with who is held."""
        tournament = self._tournament(request, tournament_pk)
        held = [service.describe(reservation) for reservation in service.active_for(tournament)]
        return Response(ReservationSerializer(held, many=True).data)

    @extend_schema(responses={200: BoardSerializer})
    def board(self, request, tournament_pk):
        """The dispatch board: every table, the ready queue in its fixed order (planned start, then
        longest wait, then id), what keeps each held-up match from a table, and which match is
        suggested for which free table."""
        return Response(BoardSerializer(board.build(self._tournament(request, tournament_pk))).data)

    @extend_schema(request=AutoDispatchSerializer, responses={200: BoardSerializer})
    def set_auto(self, request, tournament_pk):
        """Switch automatic dispatch on or off. On, ready matches go to free tables in queue order
        without anybody pressing Send; no check is ever set aside for them."""
        serializer = AutoDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            enabled = serializer.validated_data["enabled"]
            if tournament.auto_dispatch != enabled:
                tournament.auto_dispatch = enabled
                tournament.save(update_fields=["auto_dispatch", "updated_at"])
                action = matchday.Action.AUTO_ON if enabled else matchday.Action.AUTO_OFF
                matchday.log(tournament, action, tournament.name, actor=request.user)
            board.run_auto(tournament, request.user)
        return Response(BoardSerializer(board.build(tournament)).data)

    @extend_schema(request=None, responses={200: BoardSerializer})
    def run(self, request, tournament_pk):
        """Let automatic dispatch look now: it sends what it can and leaves the rest. Does nothing
        while automatic dispatch is off. The open board calls this, so a rest that has just ended is
        noticed without waiting for the next result."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            board.run_auto(tournament, request.user)
        return Response(BoardSerializer(board.build(tournament)).data)

    @extend_schema(request=DispatchSerializer, responses={200: MatchDetailSerializer})
    def dispatch_match(self, request, tournament_pk, event_pk, pk):
        """Send the match to a table. The table and the players are held from now until the result is
        official or staff call the match back. Refused with the constraint that stands in the way
        (`table_busy`, `player_busy`, `not_checked_in`, `resting`, ...); everything is checked again
        here whatever was shown before."""
        serializer = DispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            match = self._match(tournament, event_pk, pk)
            table = get_object_or_404(Table, pk=asked["table_id"])
            service.dispatch(
                match, table, request.user, overrides=asked["overrides"], reason=asked.get("reason", "")
            )
        return match_reply(request, match.draw, match.id)

    @extend_schema(request=RecallSerializer, responses={200: MatchDetailSerializer})
    def recall(self, request, tournament_pk, event_pk, pk):
        """Take the match off its table, with a reason. The table and players are free again; a score
        sheet already started stays as it is."""
        serializer = RecallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            match = self._match(tournament, event_pk, pk)
            service.recall(match, request.user, serializer.validated_data["reason"])
        return match_reply(request, match.draw, match.id)


class ControlViewSet(TournamentTables, viewsets.GenericViewSet):
    """The match-day control centre (REQ-043): calls, players reporting, moves, blocked tables, the
    check-in desk and the match-day log, for the host's competition staff. Each change answers with the
    board as it now stands."""

    permission_classes = [IsAuthenticated]
    serializer_class = BoardSerializer

    def _board(self, tournament: Tournament) -> Response:
        return Response(BoardSerializer(board.build(tournament)).data)

    @extend_schema(request=None, responses={200: BoardSerializer})
    def call(self, request, tournament_pk, event_pk, pk):
        """Call the match on a table again: the players of each side not yet at the table are told once
        more. The grace period still runs from the first call."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            control.call_again(self._match(tournament, event_pk, pk), request.user)
        return self._board(tournament)

    @extend_schema(request=ArrivalSerializer, responses={200: BoardSerializer})
    def report(self, request, tournament_pk, event_pk, pk):
        """A called side is at the table, or with `undo` isn't. Once both are, the table is warming up."""
        serializer = ArrivalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            match = self._match(tournament, event_pk, pk)
            control.report(match, asked["side"], request.user, undo=asked["undo"])
        return self._board(tournament)

    @extend_schema(request=MoveSerializer, responses={200: BoardSerializer})
    def move(self, request, tournament_pk, event_pk, pk):
        """Move a match on a table to another free table, with a reason. Its call and who has reported
        go with it; the new table is checked as any dispatch is."""
        serializer = MoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            match = self._match(tournament, event_pk, pk)
            table = get_object_or_404(control.tables_in_use(tournament), pk=asked["table_id"])
            control.move(match, table, request.user, asked["reason"])
        return self._board(tournament)

    @extend_schema(request=BlockSerializer, responses={200: BoardSerializer})
    def block(self, request, tournament_pk, table_pk):
        """Take a free table out of use, with a reason. Nothing is sent to it until it is unblocked."""
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            table = get_object_or_404(control.tables_in_use(tournament), pk=table_pk)
            control.block(tournament, table, asked["reason"], asked["note"], request.user)
        return self._board(tournament)

    @extend_schema(request=None, responses={200: BoardSerializer})
    def unblock(self, request, tournament_pk, table_pk):
        """Put a blocked table back in use."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            table = get_object_or_404(control.tables_in_use(tournament), pk=table_pk)
            control.unblock(tournament, table, request.user)
        return self._board(tournament)

    @extend_schema(request=TableUmpireSerializer, responses={200: BoardSerializer})
    def table_umpire(self, request, tournament_pk, table_pk):
        """Give a table its umpire for the tournament, or none (`user_id` null). Every match sent there
        takes them; the match waiting on it now does too if nobody has started scoring it."""
        serializer = TableUmpireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asked = serializer.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            table = get_object_or_404(control.tables_in_use(tournament), pk=table_pk)
            user = None
            if asked["user_id"]:
                listed = TournamentUmpire.objects.filter(tournament=tournament, user_id=asked["user_id"])
                found = listed.select_related("user").first()
                if found is None:
                    raise ApiException("not_listed", "Add them to the tournament's umpires first.", 409)
                user = found.user
            umpires.set_table(tournament, table, user, request.user)
        return self._board(tournament)

    @extend_schema(responses={200: DeskEntrySerializer(many=True)})
    def desk(self, request, tournament_pk):
        """The check-in desk: accepted entries of events still to play, those not checked in first.
        Checking in and undoing it use the entry's own check-in routes."""
        tournament = self._tournament(request, tournament_pk)
        return Response(DeskEntrySerializer(control.desk(tournament), many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("match", str, required=False, description="Only this match's.")],
        responses={200: MatchDayLogSerializer(many=True)},
    )
    def log(self, request, tournament_pk):
        """The match-day log, newest first (the latest 200): who did what, when and why."""
        tournament = self._tournament(request, tournament_pk)
        asked = request.query_params.get("match") or None
        try:
            match_id = uuid.UUID(asked) if asked else None
        except ValueError:  # not a match id: no entries are about it
            return Response([])
        return Response(MatchDayLogSerializer(control.log_of(tournament, match_id), many=True).data)


class UmpireListViewSet(TournamentTables, viewsets.GenericViewSet):
    """The tournament's umpires (user request, 2026-11-22), for the host's competition staff: members
    of the host and players entered in it, each optionally given a table."""

    permission_classes = [IsAuthenticated]
    serializer_class = UmpireRosterSerializer
    pagination_class = None

    def _roster(self, tournament: Tournament) -> Response:
        return Response(UmpireRosterSerializer(umpires.roster(tournament), many=True).data)

    @extend_schema(responses={200: UmpireRosterSerializer(many=True)})
    def list(self, request, tournament_pk):
        return self._roster(self._tournament(request, tournament_pk))

    @extend_schema(request=AddUmpireSerializer, responses={200: UmpireRosterSerializer(many=True)})
    def add(self, request, tournament_pk):
        """Add a member of the host, or a player entered in the tournament, to its umpires."""
        serializer = AddUmpireSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            user = umpires.eligible(tournament).filter(pk=serializer.validated_data["user_id"]).first()
            if user is None:
                raise ApiException(
                    "not_eligible",
                    "Only members of the host and players entered in this tournament can umpire here.",
                    409,
                )
            umpires.add(tournament, user, request.user)
        return self._roster(tournament)

    @extend_schema(request=None, responses={200: UmpireRosterSerializer(many=True)})
    def remove(self, request, tournament_pk, user_pk):
        """Take someone off the umpires and off their table. Matches given to them that nobody has
        started scoring go back to having no umpire, unless their role still lets them score."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            listed = get_object_or_404(
                TournamentUmpire.objects.select_related("user"), tournament=tournament, user_id=user_pk
            )
            umpires.remove(tournament, listed.user, request.user)
        return self._roster(tournament)

    @extend_schema(
        parameters=[OpenApiParameter("search", str, required=False, description="Part of a name.")],
        responses={200: UmpireCandidateSerializer(many=True)},
    )
    def candidates(self, request, tournament_pk):
        """Who can be added: members of the host and players entered, not yet on the umpires. The first
        20 by name."""
        tournament = self._tournament(request, tournament_pk)
        term = (request.query_params.get("search") or "").strip()[:80]
        found = umpires.eligible(tournament).exclude(
            id__in=TournamentUmpire.objects.filter(tournament=tournament).values("user_id")
        )
        if term:
            found = found.filter(display_name__icontains=term)
        people = found.order_by("display_name", "id")[:20]
        return Response(UmpireCandidateSerializer(people, many=True).data)
