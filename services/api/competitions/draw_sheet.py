"""An event's published draw to download: a branded PDF to print and pin up, and a PNG to share.

The PDF has every group with its members and fixtures round by round, then the knockout round by round.
The image is sized for a phone, so it shows each group's members (not the fixtures) and the knockout; a
draw too long for it is cut, and the image says so. A finished match shows its score.
"""

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from core import brand, pdf
from core.permissions import PublicReads

from . import drawing
from .models import DrawVersion, Event, Match, Tournament
from .official import title
from .results_sheet import where_and_when
from .serializers import organizer
from .views import manages

OUTCOME_MARK = {"retired": " ret.", "disqualified": " DQ"}


def side_text(side: dict | None) -> str:
    if side is None:
        return "Bye"
    if side["entry"] is None:
        return side["awaiting"]
    seed = f" [{side['seed']}]" if side["seed"] else ""
    return title(side["entry"]) + seed


def score(match: dict) -> str:
    """ "3–1", "3–1 ret.", "W/O", a team tie's rubbers; empty until the match is finished."""
    if match["status"] != Match.Status.COMPLETED:
        return ""
    if match["outcome"] == "walkover":
        return "W/O"
    if match["tie_score"] is not None:
        a, b = match["tie_score"]
    else:
        finished = [(a, b) for a, b in match["games"] if max(a, b) >= 11 and abs(a - b) >= 2]
        a = sum(1 for x, y in finished if x > y)
        b = len(finished) - a
    return f"{a}–{b}{OUTCOME_MARK.get(match['outcome'], '')}"


def match_row(match: dict) -> brand.Row:
    text = (
        side_text(match["a"])
        if match["b"] is None
        else f"{side_text(match['a'])}  v  {side_text(match['b'])}"
    )
    if match["b"] is None:
        return brand.Row(text, "Bye")
    return brand.Row(text, score(match))


def by_round(matches: list[dict]) -> list[tuple[str, list[dict]]]:
    """Matches round by round in playing order, each round named as the draw page names it."""
    rounds: dict[int, tuple[str, list[dict]]] = {}
    for match in sorted(matches, key=lambda m: (m["round"], m["position"])):
        rounds.setdefault(match["round"], (match["round_name"], []))[1].append(match)
    named = []
    for name, found in rounds.values():
        plural = len(found) > 1 and not name.startswith("Round")
        named.append((f"{name}s" if plural else name, found))
    return named


def cards(shown: dict, fixtures: bool) -> list[brand.Card]:
    """A card for each group (its members by position, then its fixtures when `fixtures`) and one for the
    knockout."""
    found = []
    single = len(shown["groups"]) == 1
    for group in shown["groups"]:
        members = sorted(
            (place for place in shown["places"] if place.group == group["number"]),
            key=lambda place: place.group_position or 0,
        )
        rows = [
            brand.Row(
                title(place.entry), f"Seed {place.seed}" if place.seed else "", badge=place.group_position
            )
            for place in members
        ]
        if fixtures:
            matches = [
                m
                for m in shown["matches"]
                if m["stage"] == Match.Stage.GROUP and m["group"] == group["number"]
            ]
            for name, played in by_round(matches):
                rows.append(brand.Row(name, note=True))
                rows += [match_row(match) for match in played]
        found.append(brand.Card("Everybody plays everybody" if single else group["name"], rows))
    knockout = [m for m in shown["matches"] if m["stage"] == Match.Stage.KNOCKOUT]
    if knockout:
        rows = []
        for name, played in by_round(knockout):
            rows.append(brand.Row(name, note=True))
            rows += [match_row(match) for match in played]
        found.append(brand.Card("Knockout", rows))
    return found


def _heading(draw: DrawVersion) -> tuple[str, str]:
    event = draw.event
    tournament = event.tournament
    return f"Draw: {event.name}", " · ".join(
        part for part in (tournament.name, where_and_when(tournament)) if part
    )


def footnote(draw: DrawVersion) -> str:
    return (
        f"Numbers in brackets are seeds. Draw version {draw.version}, rules {draw.rules_version}, "
        f"draw number {draw.rng_seed}."
    )


def as_pdf(draw: DrawVersion) -> bytes:
    shown = drawing.describe(draw)
    heading, subtitle = _heading(draw)
    blocks: list = [*cards(shown, fixtures=True)] or [pdf.Text("This draw has no matches.", muted=True)]
    blocks.append(pdf.Text(footnote(draw), muted=True))
    return pdf.document(heading, subtitle, blocks, prepared_by=organizer(draw.event.tournament)["name"])


def as_image(draw: DrawVersion) -> bytes:
    shown = drawing.describe(draw)
    heading, subtitle = _heading(draw)
    return brand.share_image(heading, subtitle, cards(shown, fixtures=False), footnote=footnote(draw))


class DrawSheetView(APIView):
    """GET /tournaments/{id}/events/{event_id}/draw.pdf and draw.png: the event's published draw, for
    whoever may see the tournament. Not found until a draw is published; a draft tournament's draw is
    its staff's."""

    permission_classes = [PublicReads]
    public_actions = ("get",)
    kind = "pdf"

    @extend_schema(
        responses={(200, "application/pdf"): OpenApiTypes.BINARY, (200, "image/png"): OpenApiTypes.BINARY}
    )
    def get(self, request, tournament_pk, event_pk):
        tournament = get_object_or_404(
            Tournament.objects.select_related("organization", "venue"), pk=tournament_pk
        )
        if tournament.status == Tournament.Status.DRAFT and not manages(
            request.user, tournament.organization
        ):
            raise Http404
        event = get_object_or_404(Event, pk=event_pk, tournament=tournament)
        draw = (
            event.draws.filter(status=DrawVersion.Status.PUBLISHED)
            .select_related("event__tournament__organization", "event__tournament__venue")
            .first()
        )
        if draw is None:
            raise Http404
        if self.kind == "png":
            response = HttpResponse(as_image(draw), content_type="image/png")
            response["Content-Disposition"] = 'inline; filename="coast-tt-draw.png"'
            return response
        response = HttpResponse(as_pdf(draw), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="coast-tt-draw.pdf"'
        return response
