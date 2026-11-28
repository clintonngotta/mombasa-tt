"""An event's published draw to download as a PDF or a PNG: every group and the knockout, scores of
finished matches, for whoever may see the tournament; nothing before a draw is published."""

import pytest
from rest_framework.test import APIClient

from competitions import drawing
from competitions.models import Match, Tournament
from competitions.official import title

from .files import pdf_text, png_size
from .test_announcements import knockout  # noqa: F401
from .test_draws import cup, draw_url, fill  # noqa: F401

pytestmark = pytest.mark.django_db


def sheet_url(tournament, event, kind: str) -> str:
    return f"/api/v1/tournaments/{tournament['id']}/events/{event['id']}/draw.{kind}"


def test_a_knockout_draw_downloads_with_its_rounds_and_scores(knockout):  # noqa: F811
    first, second = knockout["semis"]
    drawing.record_result(first, first.entry_a, games=[(11, 7), (9, 11), (11, 5), (11, 8)])
    drawing.record_result(second, second.entry_b, outcome="walkover")
    first.refresh_from_db()
    anyone = APIClient()

    response = anyone.get(sheet_url(knockout["cup"], knockout["event"], "pdf"))
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    host, event = knockout["cup"]["name"], knockout["event"]["name"]
    assert response["Content-Disposition"] == f'attachment; filename="{host} - {event} - Draw.pdf"'
    text = pdf_text(response.content)
    assert "DRAW: SINGLES" in text and knockout["cup"]["name"] in text
    assert "SEMI-FINALS" in text.upper() and "Final" in text and "KNOCKOUT" in text
    assert title(first.entry_a) in text and title(first.entry_b) in text
    assert f"{title(first.entry_a)} v {title(first.entry_b)} 3–1" in text and "W/O" in text
    second.refresh_from_db()
    assert f"Final\n{title(first.entry_a)} v {title(second.entry_b)}" in text  # the winners go through
    assert "draw number" in text and "coastloopas.org" in text

    image = anyone.get(sheet_url(knockout["cup"], knockout["event"], "png"))
    assert image.status_code == 200 and image["Content-Type"] == "image/png"
    assert png_size(image.content)[0] == 1080


def test_a_group_draw_lists_members_and_fixtures(staff, cup):  # noqa: F811
    groups = next(event for event in cup["events"] if event["name"] == "Groups")
    fill(staff, cup, groups, 6)
    staff.post(draw_url(cup, groups, "preview"), {"rng_seed": 3}, format="json")
    assert staff.post(draw_url(cup, groups, "publish"), {}, format="json").status_code == 200

    text = pdf_text(APIClient().get(sheet_url(cup, groups, "pdf")).content)
    assert "GROUP A" in text and "GROUP B" in text and "Round 1" in text
    match = Match.objects.filter(draw__event_id=groups["id"], stage=Match.Stage.GROUP).first()
    assert title(match.entry_a) in text and title(match.entry_b) in text
    assert APIClient().get(sheet_url(cup, groups, "png")).status_code == 200


def test_nothing_to_download_before_a_draw_is_published(staff, cup):  # noqa: F811
    singles = next(event for event in cup["events"] if event["name"] == "Singles")
    fill(staff, cup, singles, 4)
    staff.post(draw_url(cup, singles, "preview"), {"rng_seed": 1}, format="json")  # a preview only
    for kind in ("pdf", "png"):
        assert staff.get(sheet_url(cup, singles, kind)).status_code == 404
        assert APIClient().get(sheet_url(cup, singles, kind)).status_code == 404


def test_a_draft_tournaments_draw_is_its_staffs(staff, knockout):  # noqa: F811
    Tournament.objects.filter(pk=knockout["cup"]["id"]).update(status="draft")
    for kind in ("pdf", "png"):
        assert APIClient().get(sheet_url(knockout["cup"], knockout["event"], kind)).status_code == 404
        assert staff.get(sheet_url(knockout["cup"], knockout["event"], kind)).status_code == 200
