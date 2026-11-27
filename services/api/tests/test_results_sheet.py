"""The final results sheet (PDF and PNG): each finished event's podium with the players' clubs, in the
Coast Loopas look, for whoever may see the tournament."""

from datetime import date

from rest_framework.test import APIClient

from competitions import drawing, results_sheet
from competitions.models import Match, Tournament
from competitions.official import title
from organizations.models import Membership, Organization

from .files import pdf_text, png_size
from .test_announcements import knockout  # noqa: F401
from .test_tournaments import do


def sheet_url(game, kind: str) -> str:
    return f"/api/v1/tournaments/{game['cup']['id']}/results.{kind}"


def finish(staff, game):
    first, second = game["semis"]
    drawing.record_result(first, first.entry_a, games=[(11, 1)] * 3)
    drawing.record_result(second, second.entry_a, games=[(11, 1)] * 3)
    final = Match.objects.get(draw__event_id=game["event"]["id"], round=2)
    drawing.record_result(final, final.entry_b, games=[(1, 11)] * 3)
    do(staff, game["cup"], "complete", event=game["event"])
    final.refresh_from_db()
    return final


def test_the_sheet_lists_each_finished_event_podium_with_clubs(staff, knockout):  # noqa: F811
    anyone = APIClient()
    # Before the event is finished, the sheet says it is still being played.
    early = anyone.get(sheet_url(knockout, "pdf"))
    assert early.status_code == 200 and early["Content-Type"] == "application/pdf"
    assert "Still being played: Singles." in pdf_text(early.content)

    final = finish(staff, knockout)
    winner = final.entry_b.players.get().user
    club = Organization.objects.create(name="Nyali Loopers", town="Mombasa", kind=Organization.Kind.CLUB)
    Membership.objects.create(organization=club, user=winner)
    found = results_sheet.results(Tournament.objects.get(pk=knockout["cup"]["id"]))
    assert [(p.place, p.names, p.club) for p in found[0].placings] == [
        (1, title(final.entry_b), "Nyali Loopers"),
        (2, title(final.entry_a), results_sheet.NO_CLUB),
        (3, title(knockout["semis"][0].entry_b), results_sheet.NO_CLUB),
        (3, title(knockout["semis"][1].entry_b), results_sheet.NO_CLUB),
    ]

    response = anyone.get(sheet_url(knockout, "pdf"))
    assert "attachment" in response["Content-Disposition"]
    text = pdf_text(response.content)
    assert f"FINAL RESULTS: {knockout['cup']['name'].upper()}" in text
    assert "SINGLES" in text and title(final.entry_b) in text and "Nyali Loopers" in text
    assert "Still being played" not in text and "coastloopas.org" in text
    image = anyone.get(sheet_url(knockout, "png"))
    assert image.status_code == 200 and image["Content-Type"] == "image/png"
    assert png_size(image.content)[0] == 1080


def test_a_draft_tournaments_sheet_is_its_staffs(staff, knockout):  # noqa: F811
    Tournament.objects.filter(pk=knockout["cup"]["id"]).update(status="draft")
    for kind in ("pdf", "png"):
        assert APIClient().get(sheet_url(knockout, kind)).status_code == 404
        assert staff.get(sheet_url(knockout, kind)).status_code == 200


def test_dates_read_the_way_people_write_them():
    assert results_sheet.dates(date(2026, 11, 28), date(2026, 11, 28)) == "28 November 2026"
    assert results_sheet.dates(date(2026, 11, 28), date(2026, 11, 29)) == "28–29 November 2026"
    assert results_sheet.dates(date(2026, 11, 30), date(2026, 12, 1)) == "30 November – 1 December 2026"
    assert results_sheet.dates(date(2026, 12, 31), date(2027, 1, 1)) == "31 December 2026 – 1 January 2027"
