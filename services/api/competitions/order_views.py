"""The order of play (REQ-053, TASK-127): read by anybody who may see the tournament once it is out,
managed by the host's competition staff."""

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from accounts.models import User
from core.permissions import PublicReads

from . import order_of_play, scheduling
from .models import DrawVersion, Match, ScheduleVersion, Tournament
from .views import manages, sees_draft, staff_tournament


class StageSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    event_name = serializers.CharField(read_only=True)
    stage = serializers.ChoiceField(choices=Match.Stage.choices)
    label = serializers.CharField(read_only=True)
    placed = serializers.BooleanField(read_only=True, help_text="Placed by staff, not by default.")


class OrderSlotSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    stage = serializers.ChoiceField(choices=Match.Stage.choices)
    label = serializers.CharField()
    title = serializers.CharField(help_text="The two sides, or 'To come'.")
    table = serializers.CharField(allow_blank=True)
    scheduled_at = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=Match.Status.choices)
    on_table = serializers.BooleanField(help_text="Sent to its table.")
    mine = serializers.BooleanField(help_text="The caller plays in it.")


class NotBeforeSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    at = serializers.DateTimeField()
    note = serializers.CharField(allow_blank=True)


class EntrantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    display_name = serializers.CharField()


class OrderOfPlaySerializer(serializers.Serializer):
    published = serializers.BooleanField(help_text="A schedule has been published.")
    released = serializers.BooleanField(help_text="Everybody who sees the tournament sees it.")
    release_at = serializers.DateTimeField(allow_null=True)
    earliest_release = serializers.DateTimeField(help_text="Three days before play starts.")
    starts_at = serializers.DateTimeField(help_text="When play is due to begin.")
    version = serializers.IntegerField(allow_null=True)
    can_manage = serializers.BooleanField()
    stages = StageSerializer(many=True)
    slots = OrderSlotSerializer(many=True, help_text="Empty for everybody but staff until it is out.")
    not_before = NotBeforeSerializer(many=True, help_text="Staff only.")
    players = EntrantSerializer(many=True, help_text="Staff only: players entered, for a not-before.")


class StagesSerializer(serializers.Serializer):
    stages = StageSerializer(many=True, max_length=200)


class ReleaseSerializer(serializers.Serializer):
    release_at = serializers.DateTimeField(allow_null=True, help_text="Null: now.")


class SetNotBeforeSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    note = serializers.CharField(
        max_length=200, allow_blank=True, required=False, default="", trim_whitespace=True
    )
    move = serializers.BooleanField(
        default=True, help_text="Publish their matches planned earlier at this time, and tell people."
    )


class MoveMatchSerializer(serializers.Serializer):
    scheduled_at = serializers.DateTimeField()
    reason = serializers.ChoiceField(
        choices=[ScheduleVersion.Reason.PLAYER_REQUEST, ScheduleVersion.Reason.OTHER],
        default=ScheduleVersion.Reason.PLAYER_REQUEST,
    )
    note = serializers.CharField(
        max_length=300, allow_blank=True, required=False, default="", trim_whitespace=True
    )


def _slots(tournament: Tournament, user) -> list[dict]:
    matches = (
        Match.objects.filter(
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
            scheduled_at__isnull=False,
        )
        .exclude(status=Match.Status.BYE)
        .select_related("draw__event", "table", "planned_table", "entry_a", "entry_b", "feeder_a", "feeder_b")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
        .order_by("scheduled_at", "planned_table__position", "id")
    )
    me = user.pk if user.is_authenticated else None
    known: dict = {}
    found = []
    for match in matches:
        people = {**scheduling._people(match.entry_a), **scheduling._people(match.entry_b)}
        table = match.table or match.planned_table
        found.append(
            {
                "match_id": match.id,
                "event_id": match.draw.event_id,
                "event_name": match.draw.event.name,
                "stage": match.stage,
                "label": scheduling.label(match, known),
                "title": scheduling._title(match, known),
                "table": table.label if table else "",
                "scheduled_at": match.scheduled_at,
                "status": match.status,
                "on_table": match.dispatched_at is not None and match.status == Match.Status.SCHEDULED,
                "mine": me in people,
            }
        )
    return found


def shown(tournament: Tournament, user) -> dict:
    staff = manages(user, tournament.organization) if user.is_authenticated else False
    out = order_of_play.times_shown(tournament)
    version = tournament.schedule_versions.values_list("number", flat=True).first()
    earliest, start = order_of_play.release_window(tournament)
    nb = list(tournament.not_before.select_related("user")) if staff else []
    return {
        "published": version is not None,
        "released": out and version is not None,
        "release_at": tournament.order_of_play_release_at,
        "earliest_release": earliest,
        "starts_at": start,
        "version": version,
        "can_manage": staff,
        "stages": order_of_play.stages(tournament) if staff or out else [],
        "slots": _slots(tournament, user) if staff or out else [],
        "not_before": [
            {"user_id": row.user_id, "display_name": row.user.display_name, "at": row.at, "note": row.note}
            for row in nb
        ],
        "players": list(order_of_play.entrants(tournament).values("id", "display_name")) if staff else [],
    }


class OrderOfPlayViewSet(viewsets.GenericViewSet):
    permission_classes = [PublicReads]
    public_actions = ("retrieve",)
    serializer_class = OrderOfPlaySerializer
    pagination_class = None

    def _reply(self, tournament_pk, request) -> Response:
        tournament = Tournament.objects.select_related("organization").get(pk=tournament_pk)
        return Response(OrderOfPlaySerializer(shown(tournament, request.user)).data)

    @extend_schema(responses={200: OrderOfPlaySerializer})
    def retrieve(self, request, tournament_pk):
        """Every planned match by time and table, and the order of the stages. Staff see it as soon as
        it is published; everybody else once it is out."""
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        if tournament.status == Tournament.Status.DRAFT and not sees_draft(request.user, tournament):
            raise Http404
        return Response(OrderOfPlaySerializer(shown(tournament, request.user)).data)

    @extend_schema(request=StagesSerializer, responses={200: OrderOfPlaySerializer})
    def stages(self, request, tournament_pk):
        """Save the order of the stages, every stage once. Dispatch and the recommended schedule follow
        it from now on; the change is logged."""
        asked = StagesSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            wanted = [(row["event_id"], row["stage"]) for row in asked.validated_data["stages"]]
            order_of_play.reorder(tournament, wanted, request.user)
        return self._reply(tournament_pk, request)

    @extend_schema(request=ReleaseSerializer, responses={200: OrderOfPlaySerializer})
    def release(self, request, tournament_pk):
        """Choose when the published order of play goes public: from three days before play starts up
        to the start. Every player entered is told then."""
        asked = ReleaseSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            order_of_play.set_release(tournament, asked.validated_data["release_at"], request.user)
        return self._reply(tournament_pk, request)

    @extend_schema(request=SetNotBeforeSerializer, responses={200: OrderOfPlaySerializer})
    def set_player(self, request, tournament_pk, user_pk):
        """A player can't play before a time: the plan and dispatch respect it, and with `move` their
        matches planned earlier are published at that time at once."""
        asked = SetNotBeforeSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        data = asked.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            user = get_object_or_404(User, pk=user_pk)
            order_of_play.set_not_before(
                tournament, user, data["at"], data["note"], request.user, data["move"]
            )
        return self._reply(tournament_pk, request)

    @extend_schema(request=None, responses={200: OrderOfPlaySerializer})
    def clear_player(self, request, tournament_pk, user_pk):
        """The player may play at any time again. Their matches stay where they are."""
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            order_of_play.clear_not_before(tournament, user_pk, request.user)
        return self._reply(tournament_pk, request)

    @extend_schema(request=MoveMatchSerializer, responses={200: OrderOfPlaySerializer})
    def move(self, request, tournament_pk, match_pk):
        """Move a published match to a later start: published at once with what then clashes, and its
        people told once the order of play is out."""
        asked = MoveMatchSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        data = asked.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            order_of_play.move_match(
                tournament, match_pk, data["scheduled_at"], data["reason"], data["note"], request.user
            )
        return self._reply(tournament_pk, request)
