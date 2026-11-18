"""The day schedule editor (TASK-099), for the host's competition staff."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from facilities.models import Table

from . import scheduling
from .models import Tournament
from .views import require_staff, staff_tournament


class SlotSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    table_id = serializers.UUIDField(allow_null=True)
    scheduled_at = serializers.DateTimeField(allow_null=True)


class RecommendedSlotSerializer(SlotSerializer):
    beyond_last_day = serializers.BooleanField(help_text="It doesn't fit in the tournament's days.")


class ProblemSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    code = serializers.CharField()
    message = serializers.CharField()


class ScheduleTableSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    label = serializers.CharField()


class ScheduleRowSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event = serializers.CharField()
    label = serializers.CharField(help_text="Event, group or round, and match.")
    title = serializers.CharField(help_text="The two sides, or 'To come'.")
    minutes = serializers.IntegerField(help_text="The estimated length, from the event's best-of.")
    table_id = serializers.UUIDField(allow_null=True)
    scheduled_at = serializers.DateTimeField(allow_null=True)


class ScheduleSerializer(serializers.Serializer):
    tables = ScheduleTableSerializer(many=True)
    rows = ScheduleRowSerializer(many=True)
    conflicts = ProblemSerializer(many=True)
    warnings = ProblemSerializer(many=True)


class SlotsSerializer(serializers.Serializer):
    slots = SlotSerializer(many=True)


class CheckedSerializer(serializers.Serializer):
    conflicts = ProblemSerializer(many=True)
    warnings = ProblemSerializer(many=True)


class RecommendRequestSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(required=False, help_text="Not before; defaults to now.")
    day_starts = serializers.TimeField(required=False, default=scheduling.DAY_STARTS)
    day_ends = serializers.TimeField(required=False, default=scheduling.DAY_ENDS)
    table_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, help_text="Defaults to every table in use."
    )

    def validate(self, attrs):
        if attrs["day_ends"] <= attrs["day_starts"]:
            raise serializers.ValidationError({"day_ends": "The day must end after it starts."})
        return attrs


class RecommendationSerializer(serializers.Serializer):
    slots = RecommendedSlotSerializer(many=True)
    conflicts = ProblemSerializer(many=True)
    warnings = ProblemSerializer(many=True)


def _tables(tournament: Tournament) -> list[Table]:
    return list(Table.objects.filter(venue_id=tournament.venue_id, active=True).order_by("position"))


def _chosen(tournament: Tournament, slots: list[dict]) -> dict:
    """The slots as match id -> (table, start), refusing matches and tables that aren't this
    tournament's to plan."""
    plannable = {match.id for match in scheduling.plannable(tournament)}
    tables = {table.id: table for table in _tables(tournament)}
    chosen = {}
    for slot in slots:
        if slot["match_id"] not in plannable:
            raise ApiException(
                "not_plannable", "One of the matches is decided, on a table, or not in this tournament.", 409
            )
        table_id = slot["table_id"]
        if table_id is not None and table_id not in tables:
            raise serializers.ValidationError({"slots": "Choose a table in use at the tournament's venue."})
        chosen[slot["match_id"]] = (tables.get(table_id), slot["scheduled_at"])
    return chosen


def _checked(conflicts, warnings) -> dict:
    return {"conflicts": conflicts, "warnings": warnings}


class ScheduleViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ScheduleSerializer

    def _tournament(self, request, tournament_pk) -> Tournament:
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
        return tournament

    @extend_schema(responses={200: ScheduleSerializer})
    def retrieve(self, request, tournament_pk):
        """Every match of a published draw still to be played and not on a table, with the table and
        start planned for it, and what is wrong with the plan as it stands."""
        tournament = self._tournament(request, tournament_pk)
        return Response(
            ScheduleSerializer(
                {
                    "tables": _tables(tournament),
                    "rows": scheduling.rows(tournament),
                    **_checked(*scheduling.check(tournament, {})),
                }
            ).data
        )

    @extend_schema(request=RecommendRequestSerializer, responses={200: RecommendationSerializer})
    def recommend(self, request, tournament_pk):
        """A start and table for every match, earliest first: nobody plays twice at once or without
        their rest, and no match starts before the ones it waits for end. Nothing is saved: edit it
        and keep it with PUT."""
        tournament = self._tournament(request, tournament_pk)
        asked = RecommendRequestSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        options = asked.validated_data
        tables = _tables(tournament)
        if "table_ids" in options:
            tables = [table for table in tables if table.id in set(options["table_ids"])]
        if not tables:
            raise ApiException("no_tables", "Add a table to the venue, or choose one, to plan matches.", 409)
        slots = scheduling.recommend(
            tournament,
            tables,
            starts_at=options.get("starts_at"),
            day_starts=options["day_starts"],
            day_ends=options["day_ends"],
        )
        by_id = {table.id: table for table in tables}
        chosen = {slot["match_id"]: (by_id[slot["table_id"]], slot["scheduled_at"]) for slot in slots}
        return Response(
            RecommendationSerializer({"slots": slots, **_checked(*scheduling.check(tournament, chosen))}).data
        )

    @extend_schema(request=SlotsSerializer, responses={200: CheckedSerializer})
    def check_plan(self, request, tournament_pk):
        """What would be wrong with these changes to the plan, without keeping them."""
        tournament = self._tournament(request, tournament_pk)
        asked = SlotsSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        chosen = _chosen(tournament, asked.validated_data["slots"])
        return Response(CheckedSerializer(_checked(*scheduling.check(tournament, chosen))).data)

    @extend_schema(request=SlotsSerializer, responses={200: ScheduleSerializer})
    def update(self, request, tournament_pk):
        """Keep these tables and starts. Refused with `schedule_conflicts` and the list of conflicts
        when a table, a player or a match's order wouldn't work; warnings don't stop it."""
        asked = SlotsSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            chosen = _chosen(tournament, asked.validated_data["slots"])
            conflicts, _ = scheduling.check(tournament, chosen)
            if conflicts:
                raise ApiException(
                    "schedule_conflicts",
                    conflicts[0]["message"],
                    409,
                    extra={"conflicts": ProblemSerializer(conflicts, many=True).data},
                )
            matches = {match.id: match for match in scheduling.plannable(tournament)}
            for pk, (table, at) in chosen.items():
                match = matches[pk]
                match.planned_table, match.scheduled_at = table, at
                match.save(update_fields=["planned_table", "scheduled_at"])
        return self.retrieve(request, tournament_pk)
