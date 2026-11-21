"""The organizer's dashboard of one tournament (REQ-020, TASK-035): where every event stands, in counts,
so competition staff see at a glance what needs them next. Staff only; nothing here names a player."""

from django.db.models import Count, Exists, F, OuterRef, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from reservations.models import Reservation

from .models import Ceremony, DrawVersion, Entry, Event, Match, Resolution, Tournament
from .views import require_staff

S = Entry.Status
ENTRIES = {"pending": 0, "accepted": 0, "waitlisted": 0, "checked_in": 0}


class EntryCountsSerializer(serializers.Serializer):
    pending = serializers.IntegerField(help_text="Waiting for staff to accept or decline.")
    accepted = serializers.IntegerField()
    waitlisted = serializers.IntegerField()
    checked_in = serializers.IntegerField(help_text="Accepted entries checked in (every player).")


class MatchCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Matches of the published draw, byes left out.")
    decided = serializers.IntegerField()
    on_table = serializers.IntegerField()
    ready = serializers.IntegerField(help_text="Undecided, both sides known and not on a table.")


class EventDashboardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=Event.Status.choices)
    capacity = serializers.IntegerField(allow_null=True)
    entries = EntryCountsSerializer()
    draw = serializers.ChoiceField(choices=["none", "preview", "published"])
    matches = MatchCountsSerializer()
    corrections = serializers.IntegerField(help_text="Results corrections still to resolve.")


class TournamentDashboardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=Tournament.Status.choices)
    ceremony = serializers.ChoiceField(choices=["none", "draft", "published"])
    entries = EntryCountsSerializer()
    matches = MatchCountsSerializer()
    corrections = serializers.IntegerField()
    events = EventDashboardSerializer(many=True)


MATCHES = {"total": 0, "decided": 0, "on_table": 0, "ready": 0}


def _by_event(rows, keys) -> dict:
    return {row["event_key"]: {key: row[key] for key in keys} for row in rows}


def dashboard(tournament: Tournament) -> dict:
    """A fixed handful of grouped queries, however many events the tournament has."""
    events = list(tournament.events.all())  # programme order
    entries = _by_event(
        Entry.objects.filter(event__tournament=tournament)
        .values(event_key=F("event_id"))
        .annotate(
            pending=Count("pk", filter=Q(status=S.PENDING)),
            accepted=Count("pk", filter=Q(status=S.ACCEPTED)),
            waitlisted=Count("pk", filter=Q(status=S.WAITLISTED)),
            checked_in=Count("pk", filter=Q(status=S.ACCEPTED, checked_in_at__isnull=False)),
        ),
        ENTRIES,
    )
    draws: dict = {}
    current = DrawVersion.objects.filter(event__tournament=tournament).exclude(
        status=DrawVersion.Status.SUPERSEDED
    )
    for event_id, state in current.values_list("event_id", "status"):
        draws.setdefault(event_id, set()).add(state)
    held = Reservation.objects.filter(match=OuterRef("pk"), status=Reservation.Status.ACTIVE)
    matches = _by_event(
        Match.objects.filter(draw__event__tournament=tournament, draw__status=DrawVersion.Status.PUBLISHED)
        .exclude(status=Match.Status.BYE)
        .annotate(held=Exists(held))
        .values(event_key=F("draw__event_id"))
        .annotate(
            total=Count("pk"),
            decided=Count("pk", filter=Q(status=Match.Status.COMPLETED)),
            on_table=Count("pk", filter=Q(held=True)),
            ready=Count(
                "pk",
                filter=Q(
                    status=Match.Status.SCHEDULED,
                    entry_a__isnull=False,
                    entry_b__isnull=False,
                    held=False,
                ),
            ),
        ),
        MATCHES,
    )
    corrections = dict(
        Resolution.objects.filter(event__tournament=tournament, resolved_at__isnull=True)
        .values("event_id")
        .annotate(open=Count("pk"))
        .values_list("event_id", "open")
    )
    shown = []
    for event in events:
        states = draws.get(event.id, set())
        published = DrawVersion.Status.PUBLISHED in states
        shown.append(
            {
                "id": event.id,
                "name": event.name,
                "status": event.status,
                "capacity": event.capacity,
                "entries": entries.get(event.id, dict(ENTRIES)),
                "draw": "published"
                if published
                else "preview"
                if DrawVersion.Status.PREVIEW in states
                else "none",
                "matches": matches.get(event.id, dict(MATCHES)) if published else dict(MATCHES),
                "corrections": corrections.get(event.id, 0),
            }
        )
    ceremony = Ceremony.objects.filter(tournament=tournament).values_list("status", flat=True).first()

    def total(part: str, empty: dict) -> dict:
        return {key: sum(event[part][key] for event in shown) for key in empty}

    return {
        "id": tournament.id,
        "name": tournament.name,
        "status": tournament.status,
        "ceremony": ceremony or "none",
        "entries": total("entries", ENTRIES),
        "matches": total("matches", MATCHES),
        "corrections": sum(event["corrections"] for event in shown),
        "events": shown,
    }


class TournamentDashboardView(APIView):
    """GET /tournaments/{id}/dashboard/: the tournament's entries, check-ins, draws, matches and open
    corrections, event by event, for its host's competition staff."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: TournamentDashboardSerializer})
    def get(self, request, tournament_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_staff(request.user, tournament)
        return Response(TournamentDashboardSerializer(dashboard(tournament)).data)
