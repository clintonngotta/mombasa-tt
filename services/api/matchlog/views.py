import uuid
from collections import Counter

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from competitions.models import DrawVersion, EntryPlayer, Match, Tournament
from core.exceptions import ApiException

from .models import MatchNote, MatchResult, PersonalMatch
from .serializers import MatchNoteChangeSerializer, MatchNoteSerializer, PersonalMatchSerializer

SUGGESTED_LABELS = ["Friendly", "Tournament", "Practice", "League"]
RECENT_FORM_SIZE = 10


class MatchPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PersonalMatchViewSet(viewsets.ModelViewSet):
    """The signed-in player's own match log (REQ-037). The queryset is always scoped to the
    requester, so anyone else's record IDs resolve to 404 rather than revealing they exist."""

    serializer_class = PersonalMatchSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = MatchPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return PersonalMatch.objects.none()
        qs = PersonalMatch.objects.filter(owner=self.request.user).prefetch_related("games")
        label = self.request.query_params.get("label")
        if label:
            qs = qs.filter(label__iexact=label)
        return qs

    @extend_schema(
        parameters=[OpenApiParameter("label", str, description="Filter by label (case-insensitive)")]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        responses=inline_serializer(
            "MatchLabels", {"labels": serializers.ListField(child=serializers.CharField())}
        )
    )
    @action(detail=False)
    def labels(self, request):
        """The player's own labels, most used first, followed by default suggestions."""
        used = Counter(
            PersonalMatch.objects.filter(owner=request.user)
            .values_list("label", flat=True)
            .order_by(Lower("label"))
        )
        labels = [label for label, _ in used.most_common()]
        seen = {label.lower() for label in labels}
        labels += [s for s in SUGGESTED_LABELS if s.lower() not in seen]
        return Response({"labels": labels})

    @extend_schema(
        parameters=[OpenApiParameter("label", str, description="Limit the summary to one label")],
        responses=inline_serializer(
            "MatchStats",
            {
                "played": serializers.IntegerField(),
                "won": serializers.IntegerField(),
                "lost": serializers.IntegerField(),
                "drawn": serializers.IntegerField(),
                "win_rate": serializers.FloatField(allow_null=True),
                "games_won": serializers.IntegerField(),
                "games_lost": serializers.IntegerField(),
                "recent_form": serializers.ListField(
                    child=serializers.ChoiceField(choices=MatchResult.choices)
                ),
                "by_label": inline_serializer(
                    "LabelTally",
                    {
                        "label": serializers.CharField(),
                        "played": serializers.IntegerField(),
                        "won": serializers.IntegerField(),
                        "lost": serializers.IntegerField(),
                    },
                    many=True,
                ),
            },
        ),
    )
    @action(detail=False)
    def stats(self, request):
        matches = list(self.get_queryset())
        results = [m.result for m in matches]
        tallies = [m.tally() for m in matches]
        decided = results.count(MatchResult.WIN) + results.count(MatchResult.LOSS)

        by_label: dict[str, dict] = {}
        for match, result in zip(matches, results, strict=True):
            row = by_label.setdefault(
                match.label.lower(), {"label": match.label, "played": 0, "won": 0, "lost": 0}
            )
            row["played"] += 1
            row["won"] += result == MatchResult.WIN
            row["lost"] += result == MatchResult.LOSS

        return Response(
            {
                "played": len(matches),
                "won": results.count(MatchResult.WIN),
                "lost": results.count(MatchResult.LOSS),
                "drawn": results.count(MatchResult.DRAW),
                "win_rate": round(results.count(MatchResult.WIN) / decided, 3) if decided else None,
                "games_won": sum(w for w, _ in tallies),
                "games_lost": sum(lost for _, lost in tallies),
                # Newest first, matching the list order.
                "recent_form": results[:RECENT_FORM_SIZE],
                "by_label": sorted(by_label.values(), key=lambda r: -r["played"]),
            }
        )


def _played_by(user):
    """Official matches the user plays in: on either side, in a tournament that isn't a draft."""
    mine = EntryPlayer.objects.filter(user=user).values("entry_id")
    return (
        Match.objects.filter(Q(entry_a__in=mine) | Q(entry_b__in=mine))
        .exclude(draw__event__tournament__status=Tournament.Status.DRAFT)
        .filter(draw__status=DrawVersion.Status.PUBLISHED)
    )


class MatchNoteViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """The signed-in player's private notes on matches they played (REQ-025). Scoped to the owner: a note
    of anyone else's, or a match they didn't play, answers 404. The match itself (sets, score, result)
    is never changed here."""

    permission_classes = [IsAuthenticated]
    pagination_class = MatchPagination

    def get_serializer_class(self):
        return MatchNoteChangeSerializer if self.action == "partial_update" else MatchNoteSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MatchNote.objects.none()
        notes = MatchNote.objects.filter(owner=self.request.user).select_related(
            "personal_match",
            "match__entry_a",
            "match__entry_b",
            "match__draw__event__tournament",
        )
        if match := self.request.query_params.get("match"):
            notes = notes.filter(match_id=match) if _is_uuid(match) else notes.none()
        if own := self.request.query_params.get("personal_match"):
            notes = notes.filter(personal_match_id=own) if _is_uuid(own) else notes.none()
        return notes

    @extend_schema(
        parameters=[
            OpenApiParameter("match", str, description="Only the note on this official match."),
            OpenApiParameter("personal_match", str, description="Only the note on this recorded match."),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=MatchNoteSerializer, responses={201: MatchNoteSerializer})
    def create(self, request, *args, **kwargs):
        body = MatchNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        match_id, own_id = data.pop("match_id", None), data.pop("personal_match_id", None)
        if bool(match_id) == bool(own_id):
            raise ValidationError({"match_id": "Choose one match: an official one or one of your own."})
        # A match the player isn't in, or somebody else's record, is "not found": nothing is revealed.
        user = request.user
        match = get_object_or_404(_played_by(user), pk=match_id) if match_id else None
        own = get_object_or_404(PersonalMatch, pk=own_id, owner=user) if own_id else None
        try:
            with transaction.atomic():
                note = MatchNote.objects.create(owner=user, match=match, personal_match=own, **data)
        except IntegrityError:
            raise ApiException(
                "note_exists", "You already have notes on this match: edit them.", 409
            ) from None
        return Response(
            MatchNoteSerializer(self.get_queryset().get(pk=note.pk)).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=MatchNoteChangeSerializer, responses={200: MatchNoteSerializer})
    def partial_update(self, request, *args, **kwargs):
        note = self.get_object()
        change = MatchNoteChangeSerializer(note, data=request.data, partial=True)
        change.is_valid(raise_exception=True)
        change.save()
        return Response(MatchNoteSerializer(self.get_queryset().get(pk=note.pk)).data)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
