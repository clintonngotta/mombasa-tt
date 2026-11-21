"""Watch links (REQ-042): where a tournament, or one of its matches, is streamed on another site.

The host's competition staff add and remove links; everyone who sees the tournament sees them and can
report one. A link is https on a public host, with no password in it and on the usual port, and is
shown with its site's name so nobody clicks blind. Coast TT never embeds or fetches the page.
"""

import ipaddress
from urllib.parse import urlsplit

from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException
from core.permissions import PublicReads

from .models import LiveStream, LiveStreamReport, Match, Tournament
from .official import title as entry_title
from .views import manages, sees_draft, staff_tournament

MAX_STREAMS = 30
P = LiveStream.Platform

# Each site and the hosts its links come from (a subdomain of one counts, e.g. m.youtube.com).
PLATFORM_HOSTS = {
    P.YOUTUBE: ("youtube.com", "youtu.be"),
    P.FACEBOOK: ("facebook.com", "fb.watch", "fb.com"),
    P.INSTAGRAM: ("instagram.com",),
    P.TIKTOK: ("tiktok.com",),
    P.TWITCH: ("twitch.tv",),
    P.X: ("x.com", "twitter.com"),
    P.KICK: ("kick.com",),
}


def platform_of(host: str) -> str:
    for platform, hosts in PLATFORM_HOSTS.items():
        if any(host == known or host.endswith("." + known) for known in hosts):
            return platform
    return P.OTHER


def checked_url(value: str) -> tuple[str, str]:
    """The link as stored and the site it is on, or a ValidationError saying what is wrong with it."""
    value = value.strip()
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise serializers.ValidationError("That isn't a web address.") from error
    if parts.scheme != "https":
        raise serializers.ValidationError("Use a secure link: it starts with https://.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or "." not in host or host == "localhost" or host.endswith((".local", ".internal")):
        raise serializers.ValidationError("Use the address of a public website.")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise serializers.ValidationError("Use the site's name, not a number address.")
    if parts.username or parts.password:
        raise serializers.ValidationError("A link can't carry a username or password.")
    if port not in (None, 443):
        raise serializers.ValidationError("Use the site's usual address, without a port number.")
    return value, platform_of(host)


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


class LiveStreamSerializer(serializers.ModelSerializer):
    url = serializers.CharField(max_length=500)
    title = serializers.CharField(max_length=80, trim_whitespace=True, allow_blank=True, required=False)
    match_id = serializers.UUIDField(required=False, allow_null=True)
    domain = serializers.SerializerMethodField()
    platform_label = serializers.CharField(source="get_platform_display", read_only=True)
    report_count = serializers.SerializerMethodField(help_text="Reports so far; staff only, else null.")
    event_id = serializers.UUIDField(
        source="match.draw.event_id", read_only=True, allow_null=True, default=None
    )
    match_label = serializers.SerializerMethodField(help_text="The match's two sides, as on the draw.")

    class Meta:
        model = LiveStream
        fields = [
            "id",
            "match_id",
            "event_id",
            "match_label",
            "url",
            "domain",
            "platform",
            "platform_label",
            "title",
            "created_at",
            "report_count",
        ]
        read_only_fields = [
            "id",
            "event_id",
            "match_label",
            "domain",
            "platform",
            "platform_label",
            "created_at",
            "report_count",
        ]

    def get_domain(self, stream) -> str:
        return domain_of(stream.url)

    def get_match_label(self, stream) -> str | None:
        if stream.match is None:
            return None
        sides = [entry_title(stream.match.entry_a), entry_title(stream.match.entry_b)]
        return " v ".join(side or "To be decided" for side in sides)

    def get_report_count(self, stream) -> int | None:
        if not self.context.get("staff"):
            return None
        return getattr(stream, "reports_total", None)

    def validate_url(self, value):
        url, self._platform = checked_url(value)
        return url

    def validate(self, data):
        if "url" in data:
            data["platform"] = self._platform
        return data


class ReportSerializer(serializers.ModelSerializer):
    note = serializers.CharField(max_length=200, trim_whitespace=True, allow_blank=True, required=False)

    class Meta:
        model = LiveStreamReport
        fields = ["reason", "note"]


def _visible(user, pk) -> tuple[Tournament, bool]:
    """The tournament and whether the user runs it. A draft is 'not found' for everyone else."""
    tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=pk)
    staff = manages(user, tournament.organization)
    if tournament.status == Tournament.Status.DRAFT and not sees_draft(user, tournament):
        raise Http404
    return tournament, staff


def _listing(tournament: Tournament, staff: bool, match_id=None):
    streams = (
        LiveStream.objects.filter(tournament=tournament)
        .annotate(reports_total=Count("reports"))
        .select_related("match__draw", "match__entry_a", "match__entry_b")
        .prefetch_related("match__entry_a__players__user", "match__entry_b__players__user")
        .order_by("created_at", "id")
    )
    if match_id:
        streams = streams.filter(Q(match_id=match_id) | Q(match__isnull=True))
    return LiveStreamSerializer(streams, many=True, context={"staff": staff}).data


def _staff_tournament(request, pk) -> Tournament:
    tournament = staff_tournament(request.user, pk)
    if tournament.status in (Tournament.Status.DRAFT, Tournament.Status.CANCELLED):
        raise ApiException("not_streamable", "Publish the tournament before adding where to watch it.", 409)
    return tournament


class StreamsView(APIView):
    """GET/POST /tournaments/{id}/streams/: the tournament's watch links (with ?match=, that match's
    and the whole tournament's); staff add one for the tournament or a match."""

    permission_classes = [PublicReads]
    public_actions = ("get",)  # TASK-035

    @extend_schema(responses={200: LiveStreamSerializer(many=True)})
    def get(self, request, tournament_pk):
        tournament, staff = _visible(request.user, tournament_pk)
        match_id = request.query_params.get("match")
        if match_id:
            try:
                match_id = serializers.UUIDField().to_internal_value(match_id)
            except serializers.ValidationError as error:
                raise Http404 from error
        return Response(_listing(tournament, staff, match_id))

    @extend_schema(request=LiveStreamSerializer, responses={201: LiveStreamSerializer})
    def post(self, request, tournament_pk):
        with transaction.atomic():
            tournament = _staff_tournament(request, tournament_pk)
            serializer = LiveStreamSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            match_id = data.pop("match_id", None)
            ours = Match.objects.filter(pk=match_id, draw__event__tournament=tournament)
            if match_id and not ours.exists():
                raise serializers.ValidationError({"match_id": "Choose a match of this tournament."})
            if tournament.streams.count() >= MAX_STREAMS:
                raise ApiException("too_many_streams", f"A tournament has at most {MAX_STREAMS} links.", 409)
            if tournament.streams.filter(url=data["url"], match_id=match_id).exists():
                raise ApiException("stream_exists", "That link is already there.", 409)
            stream = LiveStream.objects.create(
                tournament=tournament, match_id=match_id, added_by=request.user, **data
            )
        stream.reports_total = 0
        shown = LiveStreamSerializer(stream, context={"staff": True}).data
        return Response(shown, status=status.HTTP_201_CREATED)


class StreamView(APIView):
    """PATCH/DELETE /tournaments/{id}/streams/{stream}/: staff change a link's address or title, or
    remove it (with its reports)."""

    permission_classes = [IsAuthenticated]

    def _stream(self, request, tournament_pk, pk) -> LiveStream:
        tournament = staff_tournament(request.user, tournament_pk)
        return get_object_or_404(LiveStream.objects.select_for_update(), pk=pk, tournament=tournament)

    @extend_schema(request=LiveStreamSerializer, responses={200: LiveStreamSerializer})
    def patch(self, request, tournament_pk, pk):
        with transaction.atomic():
            stream = self._stream(request, tournament_pk, pk)
            serializer = LiveStreamSerializer(stream, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.validated_data.pop("match_id", None)  # a link stays where it was added
            serializer.save()
        stream.reports_total = stream.reports.count()
        return Response(LiveStreamSerializer(stream, context={"staff": True}).data)

    @extend_schema(responses={204: None})
    def delete(self, request, tournament_pk, pk):
        with transaction.atomic():
            self._stream(request, tournament_pk, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReportStreamView(APIView):
    """POST /tournaments/{id}/streams/{stream}/report/: anyone who sees the tournament says what is
    wrong with a link. The host's staff see how many reports it has and decide."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReportSerializer, responses={204: None})
    def post(self, request, tournament_pk, pk):
        tournament, _ = _visible(request.user, tournament_pk)
        stream = get_object_or_404(LiveStream, pk=pk, tournament=tournament)
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        LiveStreamReport.objects.update_or_create(
            stream=stream, reporter=request.user, defaults=serializer.validated_data
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
