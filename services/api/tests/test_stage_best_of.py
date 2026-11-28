"""Longer matches as an event goes on (user request, 2026-11-28): best of 3 in the groups, best of 5 from
the quarter-finals, best of 7 in the final. A knockout stage not named plays as the stage before it."""

import pytest

from competitions import formats
from competitions.models import Event, Match
from scoring.models import Scorecard

from .helpers import logged_in
from .test_official_results import enter, fresh, hall  # noqa: F401
from .test_reservations import person, started
from .test_roles import add_member
from .test_tournaments import url
from .test_umpire_scoring import assign

pytestmark = pytest.mark.django_db


def straight(best_of: int, a_wins=True) -> list[list[int]]:
    game = [11, 5] if a_wins else [5, 11]
    return [game] * (best_of // 2 + 1)


def test_a_stage_not_named_plays_as_the_one_before_it():
    event = Event(best_of=3, best_of_by_stage={"quarter_final": 5, "final": 7})
    assert [formats.best_of_at(event, stage) for stage in formats.STAGE_KEYS] == [3, 3, 5, 5, 7]
    assert [formats.knockout_stage(n, 4) for n in (1, 2, 3, 4)] == [
        "knockout",
        "quarter_final",
        "semi_final",
        "final",
    ]
    assert formats.best_of_at(Event(best_of=5), "final") == 5


def test_each_round_of_a_knockout_is_checked_and_scored_over_its_own_best_of(staff, club, hall):  # noqa: F811
    game = started(
        staff,
        club,
        hall,
        [[f"K{n}"] for n in range(1, 9)],
        best_of=3,
        best_of_by_stage={"semi_final": 5, "final": 7},
    )
    matches = Match.objects.filter(draw__event_id=game["event"]["id"]).select_related("entry_a", "entry_b")
    draw = staff.get(url(game["cup"], event=game["event"]) + "draw/").json()["published"]
    assert {(m["round"], m["best_of"]) for m in draw["matches"]} == {(1, 3), (2, 5), (3, 7)}

    # Round one: two games won is a whole match; the semi-final needs three.
    for match in matches.filter(round=1):
        enter(staff, game, match, match.entry_a, games=straight(3))
    semi = fresh(matches.filter(round=2).first())
    refused = enter(staff, game, semi, semi.entry_a, expect=400, games=straight(3))
    assert refused["code"] == "invalid_result"
    enter(staff, game, semi, semi.entry_a, games=straight(5))

    # The umpire's sheet for the final is set up for best of 7.
    final = matches.get(round=3)
    umpire = person("Zuri Seven")
    add_member(club, umpire, "referee")
    other = fresh(matches.filter(round=2).exclude(pk=semi.pk).first())
    enter(staff, game, other, other.entry_b, games=straight(5, a_wins=False))
    assign(staff, {**game, "match": final}, umpire)
    sheet = logged_in(umpire).get(f"/api/v1/scorecards/{Scorecard.objects.get(match=final).id}/").json()
    assert sheet["config"]["best_of"] == 7


def test_stages_are_checked_and_kept_only_where_the_format_has_them(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, [["A1"], ["A2"]], format="round_robin")
    tournament = staff.get(url(game["cup"])).json()
    made = staff.post(
        url(tournament, event=False),
        {"name": "Open", "kind": "singles", "format": "knockout", "best_of_by_stage": {"final": 4}},
        format="json",
    )
    assert made.status_code == 400 and "best_of_by_stage" in made.json()["fields"]
    made = staff.post(
        url(tournament, event=False),
        {"name": "Open", "kind": "singles", "format": "knockout", "best_of_by_stage": {"last_16": 5}},
        format="json",
    )
    assert made.status_code == 400
    # A round robin has no knockout: those stages are dropped.
    made = staff.post(
        url(tournament, event=False),
        {
            "name": "League",
            "kind": "singles",
            "format": "round_robin",
            "best_of_by_stage": {"group": 5, "final": 7},
        },
        format="json",
    )
    assert made.status_code == 201
    league = next(e for e in made.json()["events"] if e["name"] == "League")
    assert league["best_of_by_stage"] == {"group": 5}


def test_the_stages_are_frozen_once_the_event_starts(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, [["F1"], ["F2"]])
    frozen = staff.patch(
        url(game["cup"], event=game["event"]), {"best_of_by_stage": {"final": 7}}, format="json"
    )
    assert (frozen.status_code, frozen.json()["code"]) == (409, "structure_frozen")
