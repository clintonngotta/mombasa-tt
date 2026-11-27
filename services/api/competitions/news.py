"""The tournament news feed (REQ-043, TASK-085): results announcements and their routes.

/tournaments/{id}/announcements/ lists what the tournament has published to everybody who may see the
tournament, and the drafts as well to its competition staff, who generate, edit, publish and amend them.
A published announcement never changes; a correction to a result it covers marks it outdated, and an
amendment is published beside it.
"""

import re
from zoneinfo import ZoneInfo

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

from core import brand, pdf
from core.exceptions import ApiException
from core.pagination import StandardPagination
from core.permissions import PublicReads
from organizations.access import effective_permissions
from organizations.permissions import Permission

from . import announcements, results_sheet
from .models import Announcement, Entry, EntryPlayer, Match, Tournament
from .serializers import organizer

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
    return get_object_or_404(Tournament.objects.select_related("organization", "venue"), pk=pk)


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
                tournament, announcements.selection_from(tournament, asked.validated_data), request.user
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

                # The players who hold a place: not those who withdrew, were turned down or wait.
                players = EntryPlayer.objects.filter(
                    entry__event__tournament=tournament, entry__status=Entry.Status.ACCEPTED
                ).values_list("user_id", flat=True)
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
            announcements.ensure_amendable(original)
            made = announcements.draft(
                tournament, announcements.Selection.of(original), request.user, amends=original
            )
        return _reply(made, status=201)


ROUND_LINE = re.compile(r"^(Final|Semi-final|Quarter-final|Round of \d+|Round \d+|Group \S+, round \d+)$")
HEAD_LINE = re.compile(r": results( of [^:]{1,40})?$")
GAMES = re.compile(r"^(.{1,300}) \((\d{1,2}-\d{1,2}(?:, \d{1,2}-\d{1,2}){0,8})\)$")
PLACE_LINE = {f"{label}: ": place for place, label in announcements.PLACE.items()}


def card_png(announcement: Announcement) -> bytes:
    """The announcement as a share image, its title in the header."""
    return brand.share_image(
        announcement.title,
        results_sheet.where_and_when(announcement.tournament),
        announcement_cards(announcement),
    )


def announcement_cards(announcement: Announcement, whole: bool = False) -> list[brand.Card]:
    """The announcement's text as cards: one per event, its matches as rows (the games on the right),
    round names and group tables as small lines, and the podium with medals. The title is in the header,
    so a first line that is the post's heading is left out. A long card is cut for the image; `whole`
    keeps every line (the PDF, which has pages)."""
    tournament = announcement.tournament
    events = set(tournament.events.values_list("name", flat=True))
    cards: list[brand.Card] = []
    lines = announcement.body.splitlines()
    # A drafted post opens with its heading ("Coast Open: results"), which the title in the header covers.
    head, title = (lines[0].strip() if lines else ""), announcement.title.strip()
    if head and (title.endswith(head) or HEAD_LINE.search(head)):
        lines = lines[1:]
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text in events:
            cards.append(brand.Card(text))
            continue
        if not cards:
            cards.append(brand.Card("Results"))
        rows = cards[-1].rows
        place = next((p for prefix, p in PLACE_LINE.items() if text.startswith(prefix)), None)
        if place is not None:
            rows.append(brand.Row(text.split(": ", 1)[1], badge=place, strong=place == 1))
        elif ROUND_LINE.match(text) or text.startswith("Rubber ") or " table" in text.split(":")[0]:
            rows.append(brand.Row(text, note=True))
        else:
            games = GAMES.match(text)
            rows.append(brand.Row(games[1], games[2]) if games else brand.Row(text))
    for card in cards:
        if not whole and len(card.rows) > CARD_ROWS:
            more = len(card.rows) - CARD_ROWS + 1
            card.rows = [
                *card.rows[: CARD_ROWS - 1],
                brand.Row(f"…and {more} more lines in the full post", note=True),
            ]
    return cards


CARD_ROWS = 18


class AnnouncementCardView(APIView):
    """GET /tournaments/{id}/announcements/{pk}/card/: the image card, for whoever may read the post."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})
    def get(self, request, tournament_pk, pk):
        tournament = _tournament(tournament_pk)
        announcement = _one(tournament, pk, _visible(request, tournament))
        response = HttpResponse(card_png(announcement), content_type="image/png")
        response["Content-Disposition"] = 'inline; filename="coast-tt-results.png"'
        return response


MAX_PDF_POSTS = 200


def announcements_pdf(tournament: Tournament, posts, single: bool = False) -> bytes:
    """The announcements as a printable document in the look of the image card: each post's events as
    cards, under when it was published. A post that a later one corrected says so. A `single` post gives
    the document its title, with the tournament named under it; in the tournament's sheet each post has
    a heading."""
    zone = ZoneInfo(tournament.timezone)
    posts = list(posts)
    blocks: list = []
    for post in posts:
        when = (
            timezone.localtime(post.published_at, zone).strftime("Published %a %d %b %Y, %H:%M")
            if post.published_at
            else "Draft"
        )
        if post.outdated_at:
            when += " · corrected by a later announcement"
        if not single:
            blocks.append(pdf.Heading(post.title))
        blocks.append(pdf.Text(when, muted=True))
        blocks += announcement_cards(post, whole=True)
    if not blocks:
        blocks.append(pdf.Text("No announcements have been published yet.", muted=True))
    return pdf.document(
        posts[0].title if single else f"Results: {tournament.name}",
        " · ".join(
            part
            for part in (
                tournament.name if single and tournament.name.lower() not in posts[0].title.lower() else "",
                results_sheet.where_and_when(tournament),
            )
            if part
        ),
        blocks,
        prepared_by=organizer(tournament)["name"],
    )


def _pdf_response(content: bytes, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{name}.pdf"'
    return response


class AnnouncementPdfView(APIView):
    """GET /tournaments/{id}/announcements/{pk}/pdf/: one announcement as a PDF, for whoever may read
    the post."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request, tournament_pk, pk):
        tournament = _tournament(tournament_pk)
        announcement = _one(tournament, pk, _visible(request, tournament))
        return _pdf_response(announcements_pdf(tournament, [announcement], single=True), "coast-tt-results")


class AnnouncementsPdfView(APIView):
    """GET /tournaments/{id}/announcements/export.pdf: every published announcement of the tournament
    in one PDF, oldest first, for whoever may see the tournament. Drafts are never included."""

    permission_classes = [PublicReads]
    public_actions = ("get",)

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request, tournament_pk):
        tournament = _tournament(tournament_pk)
        _visible(request, tournament)
        posts = list(_feed(tournament, staff=False).order_by("published_at", "id")[:MAX_PDF_POSTS])
        return _pdf_response(announcements_pdf(tournament, posts), "coast-tt-results")


class ResultsSheetView(APIView):
    """GET /tournaments/{id}/results.pdf and results.png: the final results sheet (each finished event's
    podium with the players' clubs), for whoever may see the tournament."""

    permission_classes = [PublicReads]
    public_actions = ("get",)
    kind = "pdf"

    @extend_schema(
        responses={(200, "application/pdf"): OpenApiTypes.BINARY, (200, "image/png"): OpenApiTypes.BINARY}
    )
    def get(self, request, tournament_pk):
        tournament = _tournament(tournament_pk)
        _visible(request, tournament)
        if self.kind == "png":
            response = HttpResponse(results_sheet.as_image(tournament), content_type="image/png")
            response["Content-Disposition"] = 'inline; filename="coast-tt-final-results.png"'
            return response
        return _pdf_response(results_sheet.as_pdf(tournament), "coast-tt-final-results")
