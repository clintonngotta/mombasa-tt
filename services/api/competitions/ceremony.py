"""Award ceremonies (REQ-049): the awards a tournament gives, who receives them, who presents them and
in what order.

Placement awards come from the results of completed events: first, second and the losing semi-finalists
(joint third) of a knockout, the top three of a round robin or of a Jumbles table. Staff add awards of
their own (best player, fair play, a sponsor's prize), set the order, publish the ceremony and, on the
day, mark each award presented.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.permissions import PublicReads
from organizations.access import effective_permissions
from organizations.permissions import Permission

from . import drawing
from .models import Award, Ceremony, DrawVersion, Entry, EntryPlayer, Event, Tournament
from .official import title as entry_title

PLACE_TITLE = {1: "Winner", 2: "Runner-up", 3: "Third place"}
MAX_AWARDS = 200


def podium(event: Event) -> list[tuple[int, list]]:
    """(place, entry ids) for first to third of a completed event, best first. Joint places share one."""
    if event.status != Event.Status.COMPLETED:
        return []
    draw = event.draws.filter(status=DrawVersion.Status.PUBLISHED).select_related("event").first()
    if draw is None:
        return []
    if event.kind == Event.Kind.JUMBLES or draw.format == Event.Format.ROUND_ROBIN:
        groups = sorted({g for g in draw.places.values_list("group", flat=True) if g})
        if len(groups) > 1:
            return []
        rows, complete = drawing.group_table(draw, groups[0] if groups else 1)
        if not complete:
            return []
        found: dict[int, list] = {}
        for row in rows:
            if row.rank <= 3:
                found.setdefault(row.rank, []).append(row.member)
        return sorted(found.items())
    found = []
    for placed in drawing.placements(draw):
        if placed["label"] == "Winner":
            found.append((1, placed["entry_ids"]))
        elif placed["label"] == "Runner-up":
            found.append((2, placed["entry_ids"]))
        elif placed["label"].startswith("Lost in the semi-final"):
            found.append((3, placed["entry_ids"]))
    return sorted(found)


def generate(ceremony: Ceremony) -> None:
    """Replace the placement awards not yet presented with the podiums of the completed events. Events are
    presented in reverse order of the programme, so the first event listed (usually the main one) comes
    last, and within each event third place first and the winner last."""
    tournament = ceremony.tournament
    kept = ceremony.awards.filter(kind=Award.Kind.PLACEMENT, presented_at__isnull=False)
    presented = set(kept.values_list("event_id", "place", "entry_id"))
    ceremony.awards.filter(kind=Award.Kind.PLACEMENT, presented_at__isnull=True).delete()
    order = (ceremony.awards.aggregate(last=Max("order"))["last"] or 0) + 1
    made = []
    for event in tournament.events.exclude(status=Event.Status.CANCELLED).order_by(
        "-position", "-created_at"
    ):
        for place, entry_ids in reversed(podium(event)):
            for entry_id in entry_ids:
                if (event.id, place, entry_id) in presented or (event.id, place, str(entry_id)) in presented:
                    continue
                made.append(
                    Award(
                        ceremony=ceremony,
                        kind=Award.Kind.PLACEMENT,
                        title=f"{event.name}: {PLACE_TITLE[place]}",
                        event=event,
                        place=place,
                        entry_id=entry_id,
                        order=order,
                    )
                )
                order += 1
    Award.objects.bulk_create(made)


# Serializers -----------------------------------------------------------------------------------------


class AwardSerializer(serializers.ModelSerializer):
    title = serializers.CharField(max_length=120, trim_whitespace=True)
    recipient_name = serializers.CharField(
        max_length=120, trim_whitespace=True, allow_blank=True, required=False
    )
    prize = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=True, required=False)
    presenter = serializers.CharField(max_length=120, trim_whitespace=True, allow_blank=True, required=False)
    recipient_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    event_name = serializers.CharField(source="event.name", read_only=True, allow_null=True, default=None)
    receives = serializers.SerializerMethodField()

    class Meta:
        model = Award
        fields = [
            "id",
            "order",
            "kind",
            "title",
            "event",
            "event_name",
            "place",
            "receives",
            "recipient_id",
            "recipient_name",
            "prize",
            "presenter",
            "presented_at",
        ]
        read_only_fields = ["id", "order", "kind", "event", "event_name", "place", "receives", "presented_at"]

    @extend_schema_field(serializers.CharField())
    def get_receives(self, award) -> str:
        """Who receives it, as it is announced."""
        if award.entry_id:
            return entry_title(award.entry)
        if award.recipient_id:
            return award.recipient.display_name
        return award.recipient_name


class CeremonySerializer(serializers.ModelSerializer):
    location = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=True, required=False)
    host = serializers.CharField(max_length=120, trim_whitespace=True, allow_blank=True, required=False)
    notes = serializers.CharField(max_length=1000, trim_whitespace=True, allow_blank=True, required=False)
    awards = AwardSerializer(many=True, read_only=True)

    class Meta:
        model = Ceremony
        fields = ["id", "starts_at", "location", "host", "notes", "status", "published_at", "awards"]
        read_only_fields = ["id", "status", "published_at", "awards"]


class AwardOrderSerializer(serializers.Serializer):
    awards = serializers.ListField(child=serializers.UUIDField(), max_length=MAX_AWARDS)


class HonourSerializer(serializers.Serializer):
    """An award a player received at a published ceremony."""

    id = serializers.UUIDField()
    title = serializers.CharField()
    place = serializers.IntegerField(allow_null=True)
    prize = serializers.CharField()
    tournament = serializers.UUIDField()
    tournament_name = serializers.CharField()
    held_on = serializers.DateField()


# Views -----------------------------------------------------------------------------------------------


MANAGE = Permission.COMPETITIONS_MANAGE


def _awards():
    return Award.objects.select_related("event", "recipient", "entry").prefetch_related(
        "entry__players__user"
    )


def _reply(ceremony: Ceremony, code=status.HTTP_200_OK) -> Response:
    ceremony = Ceremony.objects.prefetch_related(Prefetch("awards", queryset=_awards())).get(pk=ceremony.pk)
    return Response(CeremonySerializer(ceremony).data, status=code)


def _staff(user, tournament: Tournament) -> bool:
    return MANAGE in effective_permissions(user, tournament.organization)


def _tournament(pk) -> Tournament:
    return get_object_or_404(Tournament.objects.select_related("organization"), pk=pk)


def _staff_ceremony(request, tournament_pk, *, create=False) -> Ceremony:
    """The tournament's ceremony for its competition staff, locked; a draft or cancelled tournament has
    none. Call inside a transaction."""
    tournament = _tournament(tournament_pk)
    if not _staff(request.user, tournament):
        if tournament.status == Tournament.Status.DRAFT:
            raise Http404
        raise ApiException("permission_denied", "Only the host's competition staff run the ceremony.", 403)
    if tournament.status in (Tournament.Status.DRAFT, Tournament.Status.CANCELLED):
        raise ApiException("no_ceremony", "Publish the tournament before planning its ceremony.", 409)
    if create:
        Ceremony.objects.get_or_create(tournament=tournament)
    return get_object_or_404(Ceremony.objects.select_for_update(), tournament=tournament)


class CeremonyView(APIView):
    """GET/PUT /tournaments/{id}/ceremony/: a published ceremony for everyone who sees the tournament, a
    draft for the host's competition staff. PUT sets when, where and who hosts it."""

    permission_classes = [PublicReads]
    public_actions = ("get",)  # TASK-035

    @extend_schema(responses={200: CeremonySerializer})
    def get(self, request, tournament_pk):
        tournament = _tournament(tournament_pk)
        ceremony = Ceremony.objects.filter(tournament=tournament).first()
        if ceremony is None or (
            ceremony.status == Ceremony.Status.DRAFT and not _staff(request.user, tournament)
        ):
            raise Http404
        if tournament.status == Tournament.Status.DRAFT and not _staff(request.user, tournament):
            raise Http404
        return _reply(ceremony)

    @extend_schema(request=CeremonySerializer, responses={200: CeremonySerializer})
    def put(self, request, tournament_pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk, create=True)
            serializer = CeremonySerializer(ceremony, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return _reply(ceremony)


class GenerateAwardsView(APIView):
    """POST /tournaments/{id}/ceremony/generate/: the placement awards of the completed events, third to
    first and the main event last; awards already presented and the organizers' own are kept."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: CeremonySerializer})
    def post(self, request, tournament_pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk, create=True)
            generate(ceremony)
        return _reply(ceremony)


def took_part(tournament: Tournament, user_id) -> bool:
    """A player of the tournament, or one of its umpires: on its list of umpires or the umpire of one of
    its matches (so "Best umpire" can go to their account; user request, 2026-11-28)."""
    from reservations.models import TournamentUmpire  # reservations builds on competitions
    from scoring.models import Scorecard

    return (
        Entry.objects.filter(event__tournament=tournament, players__user=user_id).exists()
        or TournamentUmpire.objects.filter(tournament=tournament, user=user_id).exists()
        or Scorecard.objects.filter(
            Q(match__draw__event__tournament=tournament)
            | Q(rubber__match__draw__event__tournament=tournament),
            umpire=user_id,
        ).exists()
    )


def _recipient(data, tournament: Tournament):
    """A named recipient must be somebody who took part in the tournament: a player or an umpire."""
    if "recipient_id" not in data:
        return
    user_id = data.pop("recipient_id")
    data["recipient"] = None
    if user_id:
        if not took_part(tournament, user_id):
            raise serializers.ValidationError(
                {"recipient_id": "Choose a player or an umpire of this tournament."}
            )
        data["recipient"] = get_user_model().objects.get(pk=user_id)


class AwardsView(APIView):
    """POST /tournaments/{id}/ceremony/awards/: an award of the organizers' own, added last."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=AwardSerializer, responses={201: CeremonySerializer})
    def post(self, request, tournament_pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk, create=True)
            serializer = AwardSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            _recipient(data, ceremony.tournament)
            if ceremony.awards.count() >= MAX_AWARDS:
                raise ApiException("too_many_awards", "A ceremony gives at most 200 awards.", 409)
            last = ceremony.awards.aggregate(last=Max("order"))["last"]
            Award.objects.create(ceremony=ceremony, kind=Award.Kind.SPECIAL, order=(last or 0) + 1, **data)
        return _reply(ceremony, status.HTTP_201_CREATED)


class AwardView(APIView):
    """PATCH/DELETE /tournaments/{id}/ceremony/awards/{award}/: change the title, prize, presenter or a
    special award's recipient; remove it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=AwardSerializer, responses={200: CeremonySerializer})
    def patch(self, request, tournament_pk, pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk)
            award = get_object_or_404(ceremony.awards.select_for_update(), pk=pk)
            serializer = AwardSerializer(award, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            if award.kind == Award.Kind.PLACEMENT and ({"recipient_id", "recipient_name"} & set(data)):
                raise ApiException("placement_recipient", "A placement goes to whoever placed.", 409)
            _recipient(data, ceremony.tournament)
            for name, value in data.items():
                setattr(award, name, value)
            award.save()
        return _reply(ceremony)

    @extend_schema(responses={200: CeremonySerializer})
    def delete(self, request, tournament_pk, pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk)
            get_object_or_404(ceremony.awards, pk=pk).delete()
        return _reply(ceremony)


class ReorderAwardsView(APIView):
    """POST /tournaments/{id}/ceremony/reorder/ with every award id in the order they are presented."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=AwardOrderSerializer, responses={200: CeremonySerializer})
    def post(self, request, tournament_pk):
        serializer = AwardOrderSerializer(data=request.data)
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk)
            serializer.is_valid(raise_exception=True)
            wanted = [str(pk) for pk in serializer.validated_data["awards"]]
            awards = {str(a.pk): a for a in ceremony.awards.select_for_update()}
            if sorted(wanted) != sorted(awards):
                raise serializers.ValidationError({"awards": "List every award of the ceremony once."})
            for order, pk in enumerate(wanted, start=1):
                awards[pk].order = order
            Award.objects.bulk_update(awards.values(), ["order"])
        return _reply(ceremony)


class PublishCeremonyView(APIView):
    """POST /tournaments/{id}/ceremony/publish/: show the ceremony with everyone who sees the tournament."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: CeremonySerializer})
    def post(self, request, tournament_pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk)
            if not ceremony.awards.exists():
                raise ApiException("no_awards", "Add the awards before publishing the ceremony.", 409)
            if ceremony.status == Ceremony.Status.DRAFT:
                ceremony.status = Ceremony.Status.PUBLISHED
                ceremony.published_at = timezone.now()
                ceremony.save(update_fields=["status", "published_at"])
                from notifications import triggers

                players = EntryPlayer.objects.filter(
                    entry__event__tournament=ceremony.tournament
                ).values_list("user_id", flat=True)
                triggers.ceremony_published(ceremony.tournament, set(players))
        return _reply(ceremony)


class PresentAwardView(APIView):
    """POST /tournaments/{id}/ceremony/awards/{award}/present/: mark it handed over (again to undo). When
    every award is presented the ceremony is done."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: CeremonySerializer})
    def post(self, request, tournament_pk, pk):
        with transaction.atomic():
            ceremony = _staff_ceremony(request, tournament_pk)
            if ceremony.status == Ceremony.Status.DRAFT:
                raise ApiException("not_published", "Publish the ceremony before presenting awards.", 409)
            award = get_object_or_404(ceremony.awards.select_for_update(), pk=pk)
            award.presented_at = None if award.presented_at else timezone.now()
            award.save(update_fields=["presented_at"])
            done = not ceremony.awards.filter(presented_at__isnull=True).exists()
            ceremony.status = Ceremony.Status.DONE if done else Ceremony.Status.PUBLISHED
            ceremony.save(update_fields=["status"])
        return _reply(ceremony)


class MyHonoursView(APIView):
    """GET /me/honours/: awards you received at published ceremonies, newest first."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: HonourSerializer(many=True)})
    def get(self, request):
        found = (
            Award.objects.filter(Q(recipient=request.user) | Q(entry__players__user=request.user))
            .exclude(ceremony__status=Ceremony.Status.DRAFT)
            .select_related("ceremony__tournament")
            .distinct()
            .order_by("-ceremony__tournament__starts_on", "order")[:100]
        )
        rows = [
            {
                "id": award.id,
                "title": award.title,
                "place": award.place,
                "prize": award.prize,
                "tournament": award.ceremony.tournament_id,
                "tournament_name": award.ceremony.tournament.name,
                "held_on": award.ceremony.tournament.ends_on,
            }
            for award in found
        ]
        return Response(HonourSerializer(rows, many=True).data)
