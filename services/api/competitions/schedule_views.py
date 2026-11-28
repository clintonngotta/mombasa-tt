"""The day schedule editor (TASK-099), for the host's competition staff."""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.exceptions import ApiException
from facilities.models import Table
from training import club_sessions

from . import publication, scheduling
from .models import Event, ScheduleSession, ScheduleVersion, Tournament
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
    table_id = serializers.UUIDField(allow_null=True, help_text="In the working plan.")
    scheduled_at = serializers.DateTimeField(allow_null=True, help_text="In the working plan.")
    published_table_id = serializers.UUIDField(allow_null=True, help_text="As everybody sees it.")
    published_at = serializers.DateTimeField(allow_null=True, help_text="As everybody sees it.")
    unpublished = serializers.BooleanField(help_text="The working plan differs from what is published.")


class SessionSerializer(serializers.ModelSerializer):
    """A block of one day's play. No events means every event."""

    table_ids = serializers.PrimaryKeyRelatedField(
        source="tables", many=True, queryset=Table.objects.all(), help_text="At least one."
    )
    event_ids = serializers.PrimaryKeyRelatedField(
        source="events", many=True, queryset=Event.objects.all(), required=False
    )
    name = serializers.CharField(max_length=80, allow_blank=True, required=False, trim_whitespace=True)

    class Meta:
        model = ScheduleSession
        fields = ["id", "name", "day", "starts", "ends", "table_ids", "event_ids"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        tournament = self.context["tournament"]
        day = attrs.get("day", getattr(self.instance, "day", None))
        starts = attrs.get("starts", getattr(self.instance, "starts", None))
        ends = attrs.get("ends", getattr(self.instance, "ends", None))
        if day and not tournament.starts_on <= day <= tournament.ends_on:
            raise serializers.ValidationError({"day": "Choose one of the tournament's days."})
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends": "A session ends after it starts."})
        if "tables" in attrs:
            if not attrs["tables"]:
                raise serializers.ValidationError({"table_ids": "Choose at least one table."})
            if any(t.venue_id != tournament.venue_id or not t.active for t in attrs["tables"]):
                raise serializers.ValidationError({"table_ids": "Choose tables in use at the venue."})
        if any(event.tournament_id != tournament.id for event in attrs.get("events", [])):
            raise serializers.ValidationError({"event_ids": "Choose this tournament's events."})
        return attrs


class ScheduleSerializer(serializers.Serializer):
    tables = ScheduleTableSerializer(many=True)
    sessions = SessionSerializer(many=True)
    rows = ScheduleRowSerializer(many=True)
    conflicts = ProblemSerializer(many=True)
    warnings = ProblemSerializer(many=True)
    published_version = serializers.IntegerField(allow_null=True, help_text="The latest version's number.")
    notice_minutes = serializers.IntegerField(
        help_text="A published match moved by more than this, or to another table, is news for its people."
    )


class PlaceSerializer(serializers.Serializer):
    table = ScheduleTableSerializer(allow_null=True)
    scheduled_at = serializers.DateTimeField(allow_null=True)


class ChangeSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    label = serializers.CharField()
    title = serializers.CharField()
    before = PlaceSerializer()
    after = PlaceSerializer()
    notify = serializers.BooleanField(help_text="Its players and umpire are told.")


class VersionSlotSerializer(serializers.Serializer):
    match_id = serializers.UUIDField()
    label = serializers.CharField()
    title = serializers.CharField()
    table = ScheduleTableSerializer(allow_null=True)
    scheduled_at = serializers.DateTimeField(allow_null=True)


class ScheduleVersionSummarySerializer(serializers.ModelSerializer):
    published_by_name = serializers.CharField(source="published_by.display_name", default="", read_only=True)
    delayed_table = ScheduleTableSerializer(allow_null=True, read_only=True)
    change_count = serializers.SerializerMethodField()
    notify_count = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleVersion
        fields = [
            "number",
            "kind",
            "reason",
            "note",
            "delayed_table",
            "delay_minutes",
            "published_by_name",
            "published_at",
            "change_count",
            "notify_count",
            "notified_at",
            "notified_count",
        ]
        read_only_fields = fields

    def get_change_count(self, version) -> int:
        return len(version.changes)

    def get_notify_count(self, version) -> int:
        """Matches whose people are told."""
        return sum(1 for change in version.changes if change["notify"])


class ScheduleVersionSerializer(ScheduleVersionSummarySerializer):
    changes = ChangeSerializer(many=True, read_only=True)
    slots = VersionSlotSerializer(many=True, read_only=True)

    class Meta(ScheduleVersionSummarySerializer.Meta):
        fields = [*ScheduleVersionSummarySerializer.Meta.fields, "changes", "slots"]
        read_only_fields = fields


class PublishNoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, allow_blank=True, required=False, trim_whitespace=True)


class TableDelaySerializer(PublishNoteSerializer):
    table_id = serializers.UUIDField()
    minutes = serializers.IntegerField(min_value=1, max_value=480)
    reason = serializers.ChoiceField(
        choices=[
            (value, label)
            for value, label in ScheduleVersion.Reason.choices
            if value != ScheduleVersion.Reason.PLAYER_REQUEST
        ]
    )


class SetTimeSerializer(serializers.Serializer):
    """One match's table and start, published at once. A null start takes the time away."""

    table_id = serializers.UUIDField(allow_null=True)
    scheduled_at = serializers.DateTimeField(allow_null=True)
    note = serializers.CharField(
        max_length=300, allow_blank=True, required=False, default="", trim_whitespace=True
    )


class TimeSetSerializer(serializers.Serializer):
    version = ScheduleVersionSerializer()
    warnings = ProblemSerializer(many=True, help_text="For this match only: they didn't stop it.")


class DelayedSerializer(serializers.Serializer):
    version = ScheduleVersionSerializer()
    conflicts = ProblemSerializer(many=True, help_text="What the published schedule still has wrong.")
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
    use_sessions = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Plan inside the sessions (when there are any); false plans within the day's hours on "
        "every day of the tournament instead.",
    )
    table_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, help_text="Defaults to every table in use."
    )

    def validate(self, attrs):
        if attrs["day_ends"] <= attrs["day_starts"]:
            raise serializers.ValidationError({"day_ends": "The day must end after it starts."})
        return attrs


class PlannedDaySerializer(serializers.Serializer):
    day = serializers.DateField()
    matches = serializers.IntegerField()
    first_start = serializers.DateTimeField(allow_null=True)
    last_end = serializers.DateTimeField(allow_null=True)


class RecommendationSerializer(serializers.Serializer):
    slots = RecommendedSlotSerializer(
        many=True, help_text="A match no session can hold has neither table nor start."
    )
    days = PlannedDaySerializer(many=True, help_text="How the tournament's days are filled.")
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
        latest = tournament.schedule_versions.values_list("number", flat=True).first()
        return Response(
            ScheduleSerializer(
                {
                    "tables": _tables(tournament),
                    "sessions": scheduling.sessions(tournament),
                    "rows": scheduling.rows(tournament),
                    **_checked(*scheduling.check(tournament, {})),
                    "published_version": latest,
                    "notice_minutes": tournament.schedule_notice_minutes,
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
            use_sessions=options["use_sessions"],
        )
        by_id = {table.id: table for table in tables}
        chosen = {
            slot["match_id"]: (by_id[slot["table_id"]], slot["scheduled_at"])
            for slot in slots
            if slot["table_id"] is not None
        }
        return Response(
            RecommendationSerializer(
                {
                    "slots": slots,
                    "days": scheduling.days_of(tournament, slots),
                    **_checked(*scheduling.check(tournament, chosen)),
                }
            ).data
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
        """Keep these tables and starts in the working plan; nobody else sees them until the schedule
        is published. Refused with `schedule_conflicts` and the list of conflicts when a table, a
        player or a match's order wouldn't work; warnings don't stop it."""
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
                match.draft_table, match.draft_at = table, at
                match.save(update_fields=["draft_table", "draft_at"])
        return self.retrieve(request, tournament_pk)

    @extend_schema(request=SetTimeSerializer, responses={200: TimeSetSerializer})
    def set_time(self, request, tournament_pk, match_pk):
        """Set one match's table and start by hand and publish it now, without the working plan.
        Refused with `schedule_conflicts` only for conflicts this change makes; its players and
        umpire are told when a published time or table changes."""
        asked = SetTimeSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        data = asked.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            table = None
            if data["table_id"] is not None:
                table = next((t for t in _tables(tournament) if t.id == data["table_id"]), None)
                if table is None:
                    raise serializers.ValidationError({"table_id": "Choose a table in use at the venue."})
            done = publication.set_time(
                tournament, request.user, match_pk, table, data["scheduled_at"], data["note"]
            )
        return Response(TimeSetSerializer(done).data)

    @extend_schema(request=PublishNoteSerializer, responses={200: ScheduleVersionSerializer})
    def publish(self, request, tournament_pk):
        """Publish the working plan as the next version. Players and umpires of matches that move
        table, or move by more than the notice threshold, are told; nobody else. Refused with
        `schedule_conflicts` while the plan has conflicts, and `nothing_to_publish` without changes."""
        asked = PublishNoteSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            version = publication.publish(tournament, request.user, asked.validated_data.get("note", ""))
        return Response(ScheduleVersionSerializer(version).data)

    @extend_schema(request=TableDelaySerializer, responses={200: DelayedSerializer})
    def delay(self, request, tournament_pk):
        """A table starts late or goes out of service: its published matches still to play move on by
        the minutes given, and so does everything that then clashes with them. Published at once, as
        a version of its own, with the same notices as publishing."""
        asked = TableDelaySerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        options = asked.validated_data
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            table = {t.id: t for t in _tables(tournament)}.get(options["table_id"])
            if table is None:
                raise serializers.ValidationError({"table_id": "Choose a table in use at the venue."})
            done = publication.delay(
                tournament,
                request.user,
                table,
                options["minutes"],
                options["reason"],
                options.get("note", ""),
            )
        return Response(DelayedSerializer(done).data)

    @extend_schema(responses={200: ScheduleVersionSummarySerializer(many=True)})
    def versions(self, request, tournament_pk):
        """Every published version, latest first."""
        tournament = self._tournament(request, tournament_pk)
        found = tournament.schedule_versions.select_related("published_by", "delayed_table")
        return Response(ScheduleVersionSummarySerializer(found, many=True).data)

    @extend_schema(responses={200: ScheduleVersionSerializer})
    def version(self, request, tournament_pk, number):
        """One version: every match as published then, and what changed from the one before."""
        tournament = self._tournament(request, tournament_pk)
        found = get_object_or_404(
            tournament.schedule_versions.select_related("published_by", "delayed_table"), number=number
        )
        return Response(ScheduleVersionSerializer(found).data)


class ScheduleSessionViewSet(viewsets.GenericViewSet):
    """The day's sessions, for the host's competition staff."""

    permission_classes = [IsAuthenticated]
    serializer_class = SessionSerializer

    def _tournament(self, request, tournament_pk) -> Tournament:
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
        return tournament

    def list(self, request, tournament_pk):
        tournament = self._tournament(request, tournament_pk)
        return Response(SessionSerializer(scheduling.sessions(tournament), many=True).data)

    @staticmethod
    def _keep_clear_of_training(tournament, data, session=None):
        """A day session can't take tables training already holds then (REQ-044)."""
        day = data.get("day", getattr(session, "day", None))
        starts = data.get("starts", getattr(session, "starts", None))
        ends = data.get("ends", getattr(session, "ends", None))
        tables = data.get("tables", list(session.tables.all()) if session else [])
        zone = ZoneInfo(tournament.timezone)
        club_sessions.ensure_no_training_on(
            tables, datetime.combine(day, starts, tzinfo=zone), datetime.combine(day, ends, tzinfo=zone)
        )

    @transaction.atomic
    def create(self, request, tournament_pk):
        tournament = self._tournament(request, tournament_pk)
        made = SessionSerializer(data=request.data, context={"tournament": tournament})
        made.is_valid(raise_exception=True)
        self._keep_clear_of_training(tournament, made.validated_data)
        made.save(tournament=tournament)
        return Response(made.data, status=201)

    @transaction.atomic
    def partial_update(self, request, tournament_pk, pk):
        tournament = self._tournament(request, tournament_pk)
        session = get_object_or_404(tournament.schedule_sessions, pk=pk)
        changed = SessionSerializer(
            session, data=request.data, partial=True, context={"tournament": tournament}
        )
        changed.is_valid(raise_exception=True)
        self._keep_clear_of_training(tournament, changed.validated_data, session)
        changed.save()
        return Response(changed.data)

    def destroy(self, request, tournament_pk, pk):
        tournament = self._tournament(request, tournament_pk)
        get_object_or_404(tournament.schedule_sessions, pk=pk).delete()
        return Response(status=204)
