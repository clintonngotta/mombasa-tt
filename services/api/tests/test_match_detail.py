"""What the tournament tabs read (REQ-010, TASK-021): the caller's own entries pointed out in a draw,
and one match of the published draw on its own."""

from datetime import UTC, datetime

import pytest

from competitions import drawing
from competitions.models import Match
from facilities.models import Table

from .helpers import logged_in
from .test_draws import draw_url, fill
from .test_entries import enter, player
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def cup(staff, club):
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 3")
    tournament = make_tournament(staff, club, venue)
    add_event(staff, tournament, name="Singles", format="knockout")
    add_event(
        staff, tournament, name="Groups", format="groups_knockout", group_count=2, qualifiers_per_group=1
    )
    return do(staff, tournament, "publish")


def publish(staff, cup, event) -> None:
    assert staff.post(draw_url(cup, event, "preview"), {"rng_seed": 3}, format="json").status_code == 200
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200


def match_url(cup, event, match) -> str:
    return url(cup, event=event) + f"matches/{match.id}/"


def test_a_match_of_the_published_draw_is_shown_with_its_place_in_the_event(staff, cup):
    singles = cup["events"][0]
    fill(staff, cup, singles, 3)
    me = player("Zawadi")
    enter(staff, cup, singles, player_ids=[str(me.id)])
    publish(staff, cup, singles)
    viewer = logged_in(me)

    mine = [
        side["entry"]["mine"]
        for match in viewer.get(draw_url(cup, singles)).json()["published"]["matches"]
        for side in (match["a"], match["b"])
        if side and side["entry"]
    ]
    assert mine.count(True) == 1 and mine.count(False) == 3

    semi = Match.objects.filter(draw__event_id=singles["id"], round=1).order_by("position").first()
    Match.objects.filter(pk=semi.pk).update(
        table=Table.objects.get(label="Table 3"), scheduled_at=datetime(2026, 12, 5, 11, 30, tzinfo=UTC)
    )
    shown = viewer.get(match_url(cup, singles, semi))
    assert shown.status_code == 200, shown.json()
    body = shown.json()
    assert set(body) == {
        "id", "stage", "group", "round", "round_name", "position", "a", "b", "status", "winner_id",
        "outcome", "games", "tie_score", "table", "scheduled_at", "group_name", "winner_plays_in",
        "draw_version", "tie", "scoring",
    }  # fmt: skip
    assert (body["round_name"], body["winner_plays_in"], body["group_name"]) == ("Semi-final", "Final", "")
    assert (body["table"], body["scheduled_at"], body["draw_version"]) == (
        "Table 3",
        "2026-12-05T14:30:00+03:00",
        1,
    )
    assert (body["status"], body["games"], body["outcome"]) == ("scheduled", [], "")
    assert body["tie"] is None and body["tie_score"] is None  # not a team event
    assert (body["scoring"]["status"], body["scoring"]["can_score"]) == ("unassigned", False)
    assert body["scoring"]["scorecard_id"] is None and body["scoring"]["can_assign"] is False

    drawing.record_result(semi, semi.entry_a, games=[(11, 4), (9, 11), (11, 7), (11, 9)])
    done = viewer.get(match_url(cup, singles, semi)).json()
    assert (done["status"], done["outcome"], done["winner_id"]) == (
        "completed",
        "played",
        str(semi.entry_a_id),
    )
    assert done["games"] == [[11, 4], [9, 11], [11, 7], [11, 9]]

    final = Match.objects.get(draw__event_id=singles["id"], round=2)
    assert viewer.get(match_url(cup, singles, final)).json()["winner_plays_in"] == ""


def test_a_group_match_names_its_group_and_a_side_still_to_come_says_whose_place_it_is(staff, cup):
    groups = cup["events"][1]
    fill(staff, cup, groups, 5)
    publish(staff, cup, groups)
    viewer = logged_in(player("Viewer"))
    in_group = Match.objects.filter(draw__event_id=groups["id"], stage="group", group=2).first()
    body = viewer.get(match_url(cup, groups, in_group)).json()
    assert (body["group_name"], body["round_name"], body["winner_plays_in"]) == ("Group B", "Round 1", "")
    final = Match.objects.get(draw__event_id=groups["id"], stage="knockout")
    body = viewer.get(match_url(cup, groups, final)).json()
    assert body["a"] == {"entry": None, "seed": None, "awaiting": "Group A winner"}
    assert body["group_name"] == ""


def test_only_matches_of_the_published_draw_exist(staff, club, cup):
    singles = cup["events"][0]
    fill(staff, cup, singles, 4)
    publish(staff, cup, singles)
    old = Match.objects.filter(draw__event_id=singles["id"]).first()
    assert staff.post(draw_url(cup, singles, "preview"), {"rng_seed": 9}, format="json").status_code == 200
    preview = Match.objects.filter(draw__event_id=singles["id"], draw__status="preview").first()
    viewer = logged_in(player("Viewer"))
    assert viewer.get(match_url(cup, singles, preview)).status_code == 404
    assert staff.get(match_url(cup, singles, preview)).status_code == 404  # staff read it in the draw
    assert staff.post(draw_url(cup, singles, "publish"), {}, format="json").status_code == 200
    assert viewer.get(match_url(cup, singles, old)).status_code == 404  # superseded
    assert viewer.get(match_url(cup, singles, preview)).status_code == 200
    # A match isn't reached through another event.
    assert viewer.get(match_url(cup, cup["events"][1], preview)).status_code == 404

    draft = add_event(staff, make_tournament(staff, club, name="Next year"))
    hidden = url(draft, event=draft["events"][0]) + f"matches/{preview.id}/"
    assert viewer.get(hidden).status_code == 404
