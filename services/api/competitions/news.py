"""The tournament news feed (REQ-043, TASK-085): results announcements and their routes.

/tournaments/{id}/announcements/ lists what the tournament has published to everybody who may see the
tournament, and the drafts as well to its competition staff, who generate, edit, publish and amend them.
A published announcement never changes; a correction to a result it covers marks it outdated, and an
amendment is published beside it.
"""

import textwrap
from html import escape

from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.pagination import StandardPagination
from core.permissions import PublicReads
from organizations.access import effective_permissions
from organizations.permissions import Permission

from . import announcements
from .models import Announcement, EntryPlayer, Match, Tournament
from .recap import GOLD, MUTED, NAVY, WHITE

Scope = Announcement.Scope


class AnnouncementSerializer(serializers.ModelSerializer):
    event_id = serializers.UUIDField(allow_null=True, read_only=True)
    event_name = serializers.SerializerMethodField()
    session_id = serializers.UUIDField(allow_null=True, read_only=True)
    amends_id = serializers.UUIDField(allow_null=True, read_only=True)
    amended_by_id = serializers.SerializerMethodField(help_text="The published amendment, once there is one.")

    class Meta:
        model = Announcement
        fields = [
            "id",
            "scope",
            "event_id",
            "event_name",
            "stage",
            "round",
            "day",
            "session_id",
            "title",
            "body",
            "status",
            "created_at",
            "published_at",
            "outdated_at",
            "amends_id",
            "amended_by_id",
        ]
        read_only_fields = fields

    def get_event_name(self, announcement) -> str:
        return announcement.event.name if announcement.event else ""

    def get_amended_by_id(self, announcement) -> str | None:
        published = [a for a in announcement.amendments.all() if a.status == Announcement.Status.PUBLISHED]
        return str(published[-1].id) if published else None


class GenerateSerializer(serializers.Serializer):
    """What to announce: `event_id` for an event or a round, with `stage` and `round` for a round, `day`
    for a day (venue local) and `session_id` for a session."""

    scope = serializers.ChoiceField(choices=Scope.choices)
    event_id = serializers.UUIDField(required=False)
    stage = serializers.ChoiceField(choices=Match.Stage.choices, required=False)
    round = serializers.IntegerField(required=False, min_value=1, max_value=64)
    day = serializers.DateField(required=False)
    session_id = serializers.UUIDField(required=False)


class EditSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=announcements.MAX_TITLE, required=False)
    body = serializers.CharField(max_length=announcements.MAX_BODY, required=False, trim_whitespace=False)


class PublishSerializer(serializers.Serializer):
    notify = serializers.BooleanField(default=False, help_text="Tell the tournament's players it is out.")


def _tournament(pk) -> Tournament:
    return get_object_or_404(Tournament.objects.select_related("organization"), pk=pk)


def _staff(user, tournament: Tournament) -> bool:
    return Permission.COMPETITIONS_MANAGE in effective_permissions(user, tournament.organization)


def _visible(request, tournament: Tournament) -> bool:
    """Whether the caller sees the tournament's drafts too, after refusing one it may not see at all."""
    staff = _staff(request.user, tournament)
    if tournament.status == Tournament.Status.DRAFT and not staff:
        raise Http404
    return staff


def _staff_tournament(request, tournament_pk) -> Tournament:
    tournament = get_object_or_404(
        Tournament.objects.select_for_update(of=("self",)).select_related("organization"), pk=tournament_pk
    )
    if not _staff(request.user, tournament):
        if tournament.status == Tournament.Status.DRAFT:
            raise Http404
        raise ApiException("permission_denied", "Only the host's competition staff write announcements.", 403)
    return tournament


def _feed(tournament: Tournament, staff: bool):
    found = Announcement.objects.filter(tournament=tournament).select_related("event")
    if not staff:
        found = found.filter(status=Announcement.Status.PUBLISHED)
    return found.prefetch_related(
        Prefetch("amendments", queryset=Announcement.objects.order_by("published_at", "created_at"))
    )


def _one(tournament: Tournament, pk, staff: bool) -> Announcement:
    found = _feed(tournament, staff).filter(pk=pk).first()
    if found is None:
        raise Http404
    return found


def _reply(announcement: Announcement, status=200) -> Response:
    fresh = _one(announcement.tournament, announcement.pk, staff=True)
    return Response(AnnouncementSerializer(fresh).data, status=status)


class AnnouncementsView(GenericAPIView):
    """GET /tournaments/{id}/announcements/: the news feed, newest first (drafts too for the staff).
    POST: generate a draft from the official results of a session, round, day, event or the tournament."""

    permission_classes = [PublicReads]
    public_actions = ("get",)
    pagination_class = StandardPagination
    serializer_class = AnnouncementSerializer

    @extend_schema(responses={200: AnnouncementSerializer(many=True)})
    def get(self, request, tournament_pk):
        tournament = _tournament(tournament_pk)
        page = self.paginate_queryset(_feed(tournament, _visible(request, tournament)))
        return self.get_paginated_response(AnnouncementSerializer(page, many=True).data)

    @extend_schema(request=GenerateSerializer, responses={201: AnnouncementSerializer})
    def post(self, request, tournament_pk):
        asked = GenerateSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = _staff_tournament(request, tournament_pk)
            made = announcements.draft(
                tournament, announcements.scoped_from(tournament, asked.validated_data), request.user
            )
        return _reply(made, status=201)


class AnnouncementView(APIView):
    """GET/PATCH/DELETE /tournaments/{id}/announcements/{pk}/: one announcement. Only a draft is edited
    or deleted; a published one is frozen."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={200: AnnouncementSerializer})
    def get(self, request, tournament_pk, pk):
        tournament = _tournament(tournament_pk)
        return Response(AnnouncementSerializer(_one(tournament, pk, _visible(request, tournament))).data)

    @extend_schema(request=EditSerializer, responses={200: AnnouncementSerializer})
    def patch(self, request, tournament_pk, pk):
        asked = EditSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = _staff_tournament(request, tournament_pk)
            announcement = _locked(tournament, pk)
            announcements.ensure_draft(announcement)
            changed = [field for field in ("title", "body") if field in asked.validated_data]
            for field in changed:
                setattr(announcement, field, asked.validated_data[field])
            if not (announcement.title.strip() and announcement.body.strip()):
                raise ApiException(
                    "invalid_announcement", "An announcement needs a title and some text.", 400
                )
            announcement.save(update_fields=changed)
        return _reply(announcement)

    @extend_schema(responses={204: None})
    def delete(self, request, tournament_pk, pk):
        with transaction.atomic():
            tournament = _staff_tournament(request, tournament_pk)
            announcement = _locked(tournament, pk)
            announcements.ensure_draft(announcement)
            announcement.delete()
        return Response(status=204)


def _locked(tournament: Tournament, pk) -> Announcement:
    return get_object_or_404(Announcement.objects.select_for_update(), tournament=tournament, pk=pk)


class PublishAnnouncementView(APIView):
    """POST /tournaments/{id}/announcements/{pk}/publish/: put it on the feed, frozen from now on, and
    optionally tell the tournament's players."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=PublishSerializer, responses={200: AnnouncementSerializer})
    def post(self, request, tournament_pk, pk):
        asked = PublishSerializer(data=request.data)
        asked.is_valid(raise_exception=True)
        with transaction.atomic():
            tournament = _staff_tournament(request, tournament_pk)
            announcement = _locked(tournament, pk)
            announcements.ensure_draft(announcement)
            announcement.status = Announcement.Status.PUBLISHED
            announcement.published_at = timezone.now()
            announcement.published_by = request.user
            announcement.save(update_fields=["status", "published_at", "published_by"])
            if asked.validated_data["notify"]:
                from notifications import triggers

                players = EntryPlayer.objects.filter(entry__event__tournament=tournament).values_list(
                    "user_id", flat=True
                )
                triggers.results_announced(announcement, set(players))
        return _reply(announcement)


class AmendAnnouncementView(APIView):
    """POST /tournaments/{id}/announcements/{pk}/amend/: a new draft of a published announcement, drawn
    again from the official results as they stand now. The original stays on the feed."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={201: AnnouncementSerializer})
    def post(self, request, tournament_pk, pk):
        with transaction.atomic():
            tournament = _staff_tournament(request, tournament_pk)
            original = _locked(tournament, pk)
            if original.status != Announcement.Status.PUBLISHED:
                raise ApiException(
                    "not_published", "Edit the draft itself; only a published one is amended.", 409
                )
            made = announcements.draft(
                tournament, announcements.scoped_of(original), request.user, amends=original
            )
        return _reply(made, status=201)


CARD_LINES = 14
CARD_WIDTH = 46


def card_svg(announcement: Announcement) -> str:
    """A 1080x1080 card of the announcement's text, in the result card's colours: the title, then as many
    lines as fit and how many more there are."""
    lines = []
    for paragraph in announcement.body.splitlines()[1:]:  # the first line is the heading, shown as the title
        lines.extend(textwrap.wrap(paragraph, CARD_WIDTH) or [""])
    while lines and not lines[0]:
        lines.pop(0)
    shown, rest = lines[:CARD_LINES], len(lines) - CARD_LINES
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080">',
        f'<rect width="1080" height="1080" fill="{NAVY}"/>',
        f'<rect x="0" y="0" width="1080" height="16" fill="{GOLD}"/>',
        f'<text x="80" y="120" fill="{GOLD}" font-family="sans-serif" font-size="36" '
        'font-weight="700">COAST TT</text>',
    ]
    for number, line in enumerate(textwrap.wrap(announcement.title, 34)[:2]):
        out.append(
            f'<text x="80" y="{190 + number * 52}" fill="{WHITE}" font-family="sans-serif" font-size="44" '
            f'font-weight="700">{escape(line)}</text>'
        )
    for number, line in enumerate(shown):
        out.append(
            f'<text x="80" y="{320 + number * 50}" fill="{WHITE}" font-family="sans-serif" '
            f'font-size="32">{escape(line)}</text>'
        )
    if rest > 0:
        out.append(
            f'<text x="80" y="1030" fill="{MUTED}" font-family="sans-serif" font-size="30">'
            f"…and {rest} more line{'s' if rest != 1 else ''} in the full post</text>"
        )
    out.append("</svg>")
    return "\n".join(out)


class AnnouncementCardView(APIView):
    """GET /tournaments/{id}/announcements/{pk}/card/: the image card, for whoever may read the post."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={(200, "image/svg+xml"): OpenApiTypes.STR})
    def get(self, request, tournament_pk, pk):
        tournament = _tournament(tournament_pk)
        announcement = _one(tournament, pk, _visible(request, tournament))
        response = HttpResponse(card_svg(announcement), content_type="image/svg+xml")
        response["Content-Disposition"] = 'inline; filename="coast-tt-results.svg"'
        return response
