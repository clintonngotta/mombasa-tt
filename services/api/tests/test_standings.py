"""Group ranking and qualification (REQ-010, EVAL-010, TASK-020).

Expected ranks, match points and ratios are worked out by hand from ITTF Statutes 2026, 3.7.5 (spec.md)
and listed as fixtures F-ST1 to F-ST8 in test.md, never taken from the code under test.
"""

import pytest

from competitions import drawing, standings
from competitions.models import Entry, Match
from competitions.standings import RETIRED, WALKOVER, Result, rank

from .helpers import logged_in
from .test_draws import draw_url, fill
from .test_entries import player
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
MEMBERS = ["A", "B", "C", "D"]


def beat(winner: str, loser: str, score: str = "3-0", games=None) -> Result:
    """A played match. Without explicit games the winner's games are 11-5 and the loser's 5-11."""
    won, lost = (int(n) for n in score.split("-"))
    return Result(winner, loser, games=tuple(games or [(11, 5)] * won + [(5, 11)] * lost))


def order(rows) -> str:
    return "".join(row.member for row in rows)


def steps(rows, member) -> list[tuple]:
    row = next(row for row in rows if row.member == member)
    return [("".join(step.among), step.measure, step.value) for step in row.steps]


def test_fst1_no_ties_rank_by_match_points():
    results = [beat("A", "B"), beat("A", "C"), beat("A", "D"), beat("B", "C"), beat("B", "D"), beat("C", "D")]
    rows = rank(MEMBERS, results)
    assert order(rows) == "ABCD"
    assert [(r.rank, r.played, r.won, r.lost, r.match_points) for r in rows] == [
        (1, 3, 3, 0, 6),
        (2, 3, 2, 1, 5),
        (3, 3, 1, 2, 4),
        (4, 3, 0, 3, 3),
    ]
    assert all(row.steps == [] and not row.level for row in rows)


def test_fst2_two_level_pairs_are_each_decided_by_their_own_match():
    results = [beat("A", "B"), beat("A", "C"), beat("D", "A"), beat("B", "C"), beat("B", "D"), beat("C", "D")]
    rows = rank(MEMBERS, results)
    assert [row.match_points for row in rows] == [5, 5, 4, 4]
    assert order(rows) == "ABCD"  # A beat B; C beat D
    assert steps(rows, "A") == [("AB", "match_points", "2")]
    assert steps(rows, "B") == [("AB", "match_points", "1")]
    assert steps(rows, "D") == [("CD", "match_points", "1")]


def test_fst3_three_level_members_are_separated_by_games_between_them():
    results = [
        beat("A", "B", "3-0"),
        beat("B", "C", "3-1"),
        beat("C", "A", "3-2"),
        beat("A", "D"),
        beat("B", "D"),
        beat("C", "D"),
    ]
    rows = rank(MEMBERS, results)
    assert [row.match_points for row in rows] == [5, 5, 5, 3]
    assert order(rows) == "ACBD"  # games between them: A 5/3, C 4/5, B 3/4
    assert steps(rows, "A") == [("ABC", "match_points", "3"), ("ABC", "games", "5/3")]
    assert steps(rows, "C") == [("ABC", "match_points", "3"), ("ABC", "games", "4/5")]
    assert steps(rows, "B") == [("ABC", "match_points", "3"), ("ABC", "games", "3/4")]
    # The table still shows everybody's whole record, D's matches included.
    a = rows[0]
    assert (a.games_won, a.games_lost) == (8, 3)


def test_fst4_level_on_games_too_the_points_between_them_decide():
    results = [
        beat("A", "B", games=[(11, 5), (11, 7), (9, 11), (11, 8)]),
        beat("B", "C", games=[(11, 9), (11, 9), (8, 11), (11, 9)]),
        beat("C", "A", games=[(11, 6), (12, 10), (5, 11), (11, 9)]),
        beat("A", "D"),
        beat("B", "D"),
        beat("C", "D"),
    ]
    rows = rank(MEMBERS, results)
    assert order(rows) == "ACBD"  # points between them: A 78/70, C 77/77, B 72/80
    assert steps(rows, "A") == [
        ("ABC", "match_points", "3"),
        ("ABC", "games", "4/4"),
        ("ABC", "points", "78/70"),
    ]
    assert steps(rows, "C")[-1] == ("ABC", "points", "77/77")
    assert steps(rows, "B")[-1] == ("ABC", "points", "72/80")


def test_fst5_an_unplayed_loss_scores_nothing_and_those_still_level_start_again():
    results = [
        beat("A", "B"),
        beat("A", "D"),
        Result("C", "A", WALKOVER),
        beat("B", "C"),
        beat("D", "B"),
        beat("D", "C"),
    ]
    rows = rank(MEMBERS, results)
    assert {row.member: row.match_points for row in rows} == {"A": 4, "B": 4, "C": 4, "D": 5}
    # Between A, B and C: A 2, B 3, C 3. A is settled last of them; B and C start again on their own
    # match, which B won (3.7.5.3).
    assert order(rows) == "DBCA"
    assert steps(rows, "A") == [("ABC", "match_points", "2")]
    assert steps(rows, "B") == [("ABC", "match_points", "3"), ("BC", "match_points", "2")]
    assert steps(rows, "C") == [("ABC", "match_points", "3"), ("BC", "match_points", "1")]
    # The walkover counts 3-0 and 11-0 a game to C.
    c = next(row for row in rows if row.member == "C")
    assert (c.games_won, c.games_lost, c.points_won, c.points_lost) == (3, 6, 33 + 15 + 15, 33 + 33)


def test_fst6_what_nothing_separates_is_drawn_by_lot_once_the_group_is_finished():
    results = [beat("A", "B"), beat("B", "C"), beat("C", "A"), beat("A", "D"), beat("B", "D"), beat("C", "D")]
    rows = rank(MEMBERS, results, lot_seed=4)
    assert sorted(order(rows)[:3]) == ["A", "B", "C"] and rows[3].member == "D"
    for member in "ABC":
        assert steps(rows, member) == [
            ("ABC", "match_points", "3"),
            ("ABC", "games", "3/3"),
            ("ABC", "points", "48/48"),
            ("ABC", "lot", ""),
        ]
    assert order(rank(MEMBERS, results, lot_seed=4)) == order(rows)  # the same lot every time
    assert len({order(rank(MEMBERS, results, lot_seed=n)) for n in range(30)}) > 1

    # While matches are still to play nothing is drawn: the three are shown level, in group order.
    early = rank(MEMBERS, results[:3], final=False)  # only the three matches between A, B and C
    assert order(early) == "ABCD" and [row.level for row in early] == [True, True, True, False]
    assert all(step[1] != "lot" for member in "ABC" for step in steps(early, member))


def test_fst7_a_member_who_forfeits_loses_every_match_unplayed():
    results = [beat("A", "B"), beat("A", "C"), beat("D", "A"), beat("B", "C"), beat("B", "D"), beat("C", "D")]
    rows = rank(MEMBERS, results, forfeited={"D"})
    assert order(rows) == "ABCD"
    assert [row.match_points for row in rows] == [6, 5, 4, 0]
    d = rows[3]
    assert (d.won, d.lost, d.games_won, d.points_won) == (0, 3, 0, 0)


def test_fst8_unfinished_and_unplayed_matches_are_completed_in_the_winners_favour():
    retired = Result("X", "Y", RETIRED, games=((11, 9), (5, 11), (4, 2)))
    assert standings.credited_games(retired) == [(11, 9), (5, 11), (11, 2), (11, 0)]
    assert standings.credited_games(Result("X", "Y", WALKOVER, best_of=7)) == [(11, 0)] * 4
    deuce = Result("X", "Y", RETIRED, games=((10, 12), (10, 11)), best_of=3)
    assert standings.credited_games(deuce) == [(10, 12), (13, 11), (11, 0)]
    rows = rank(["X", "Y"], [retired])
    assert [(r.member, r.match_points, r.games_won, r.points_won) for r in rows] == [
        ("X", 2, 3, 38),
        ("Y", 0, 1, 22),
    ]


def test_ratios_are_compared_exactly_never_rounded():
    """10/9 and 11/10 both show as 1.1 to one decimal; 10/9 is the better ratio."""
    results = [
        beat("A", "B", games=[(10, 0)] * 3),  # stylised scores to pin the ratios exactly
        beat("B", "C", games=[(11, 1)] * 3),
        beat("C", "A", games=[(11, 9)] * 3),
    ]
    rows = rank(["A", "B", "C"], results)
    points = {row.member: steps(rows, row.member)[-1][2] for row in rows}
    assert points == {"A": "57/33", "B": "33/33", "C": "36/60"}
    close = [
        beat("A", "B", games=[(10, 9)]),
        beat("B", "C", games=[(11, 10)]),
        beat("C", "A", games=[(100, 99)]),
    ]
    # A: 109/109, B: 20/20, C: 110/110 are all exactly 1, so only the lot can separate them.
    assert steps(rank(["A", "B", "C"], close), "A")[-1][1] == "lot"
    tally_a, tally_b = standings._Tally(), standings._Tally()
    tally_a.for_["points"], tally_a.against["points"] = 10, 9
    tally_b.for_["points"], tally_b.against["points"] = 11, 10
    assert tally_a.key("points") > tally_b.key("points")
    unbeaten = standings._Tally()
    unbeaten.for_["games"] = 3
    assert unbeaten.key("games") > tally_a.key("points")  # nothing lost beats any ratio


def test_a_team_event_looks_at_individual_matches_before_games():
    results = [
        Result("A", "B", games=((11, 5),) * 3, rubbers=(3, 0)),
        Result("B", "C", games=((11, 5),) * 3, rubbers=(3, 1)),
        Result("C", "A", games=((11, 5),) * 3, rubbers=(3, 2)),
    ]
    rows = rank(["A", "B", "C"], results, team=True)
    assert order(rows) == "ACB"
    assert steps(rows, "A") == [("ABC", "match_points", "3"), ("ABC", "rubbers", "5/3")]


# --- Kept standings and qualification (API) ------------------------------------------------------


@pytest.fixture
def cup(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(
        staff, tournament, name="Groups", format="groups_knockout", group_count=2, qualifiers_per_group=1
    )
    add_event(staff, tournament, name="League", format="round_robin")
    add_event(
        staff, tournament, name="Three", format="groups_knockout", group_count=3, qualifiers_per_group=1
    )
    return do(staff, tournament, "publish")


def published(staff, cup, event, count) -> None:
    fill(staff, cup, event, count)
    staff.post(draw_url(cup, event, "preview"), {"rng_seed": 5}, format="json")
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200


def standings_of(client, cup, event) -> dict:
    response = client.get(url(cup, event=event) + "standings/")
    assert response.status_code == 200, response.json()
    return response.json()


def decide(match: Match, a_wins: bool, games=((11, 5), (11, 5), (11, 5))) -> None:
    winner = match.entry_a if a_wins else match.entry_b
    drawing.record_result(match, winner, games=games if a_wins else [(b, a) for a, b in games])


def test_a_finished_group_sends_its_winner_into_the_knockout(staff, cup):
    groups = cup["events"][0]
    viewer = logged_in(player("Viewer"))
    assert standings_of(viewer, cup, groups) == {"rules_version": "", "groups": [], "placements": []}
    published(staff, cup, groups, 5)  # groups of 3 and 2

    before = standings_of(viewer, cup, groups)
    assert [(g["name"], g["complete"], g["qualifiers"], len(g["rows"])) for g in before["groups"]] == [
        ("Group A", False, 1, 3),
        ("Group B", False, 1, 2),
    ]
    assert all(row["qualified"] is None and row["level"] for g in before["groups"] for row in g["rows"])
    assert before["placements"] == [] and before["rules_version"] == "ITTF-2026-ch3"

    final = Match.objects.get(stage="knockout", draw__event_id=groups["id"])
    assert final.entry_a is None and final.entry_b is None
    for match in Match.objects.filter(stage="group", group=1, draw__event_id=groups["id"]):
        decide(match, a_wins=True)
    only = Match.objects.get(stage="group", group=2, draw__event_id=groups["id"])
    final.refresh_from_db()
    assert final.entry_a is not None and final.entry_b is None  # group B is still playing

    table = standings_of(viewer, cup, groups)["groups"][0]
    assert table["complete"] is True
    assert [(r["rank"], r["match_points"], r["qualified"]) for r in table["rows"]] == [
        (1, 4, True),
        (2, 3, False),
        (3, 2, False),
    ]
    assert str(final.entry_a_id) == table["rows"][0]["entry"]["id"]
    assert set(table["rows"][0]) == {
        "rank", "entry", "played", "won", "lost", "match_points", "games_won", "games_lost",
        "points_won", "points_lost", "level", "qualified", "tie_break",
    }  # fmt: skip

    decide(only, a_wins=False)
    final.refresh_from_db()
    assert final.entry_b == only.entry_b
    decide(final, a_wins=True)
    placed = standings_of(viewer, cup, groups)["placements"]
    assert [(p["label"], [e["id"] for e in p["entries"]]) for p in placed] == [
        ("Winner", [str(final.entry_a_id)]),
        ("Runner-up", [str(final.entry_b_id)]),
    ]


def test_a_round_robin_event_is_one_table_with_its_tie_breaks_explained(staff, cup):
    league = cup["events"][1]
    published(staff, cup, league, 3)
    matches = {(m.entry_a_id, m.entry_b_id): m for m in Match.objects.filter(draw__event_id=league["id"])}
    places = {p.group_position: p.entry for p in matches[next(iter(matches))].draw.places.all()}
    one, two, three = places[1], places[2], places[3]

    def play(winner: Entry, loser: Entry, games):
        match = matches.get((winner.id, loser.id)) or matches[loser.id, winner.id]
        a_won = match.entry_a_id == winner.id
        drawing.record_result(match, winner, games=games if a_won else [(b, a) for a, b in games])

    # F-ST3 shape: one beats two 3-0, two beats three 3-1, three beats one 3-2.
    play(one, two, [(11, 5)] * 3)
    play(two, three, [(11, 5), (11, 5), (5, 11), (11, 5)])
    play(three, one, [(11, 5), (5, 11), (11, 5), (5, 11), (11, 5)])
    table = standings_of(staff, cup, league)["groups"][0]
    assert table["qualifiers"] == 0 and table["complete"] is True
    assert [r["entry"]["id"] for r in table["rows"]] == [str(one.id), str(three.id), str(two.id)]
    assert all(r["qualified"] is None for r in table["rows"])
    assert table["rows"][0]["tie_break"] == [
        {"among": [str(one.id), str(two.id), str(three.id)], "measure": "match_points", "value": "3"},
        {"among": [str(one.id), str(two.id), str(three.id)], "measure": "games", "value": "5/3"},
    ]


def test_a_qualifier_with_a_bye_goes_straight_to_the_next_round(staff, cup):
    three = cup["events"][2]
    published(staff, cup, three, 6)
    knockout = list(
        Match.objects.filter(stage="knockout", draw__event_id=three["id"]).order_by("round", "position")
    )
    bye, semi, final = knockout
    assert (bye.status, bye.a_from_group, bye.winner) == ("bye", 1, None)
    group_a = Match.objects.get(stage="group", group=1, draw__event_id=three["id"])
    decide(group_a, a_wins=True)
    bye.refresh_from_db()
    final.refresh_from_db()
    assert bye.winner == group_a.entry_a and final.entry_a == group_a.entry_a and final.entry_b is None
    # The other groups fill the semi-final; only then is there anything to place.
    for number in (2, 3):
        decide(Match.objects.get(stage="group", group=number, draw__event_id=three["id"]), a_wins=True)
    semi.refresh_from_db()
    assert semi.entry_a is not None and semi.entry_b is not None
    assert standings_of(staff, cup, three)["placements"] == []
    decide(semi, a_wins=True)
    placed = standings_of(staff, cup, three)["placements"]
    assert [p["label"] for p in placed] == ["Lost in the semi-final"]
    assert [e["id"] for e in placed[0]["entries"]] == [str(semi.entry_b_id)]


def test_standings_follow_the_tournaments_visibility(staff, club, cup):
    draft = add_event(staff, make_tournament(staff, club, name="Next year"))
    path = url(draft, event=draft["events"][0]) + "standings/"
    assert logged_in(player("Viewer")).get(path).status_code == 404
    assert staff.get(path).status_code == 200
