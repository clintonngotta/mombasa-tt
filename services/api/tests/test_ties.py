"""Team ties (REQ-011, EVAL-011, TASK-022): the tie format of a team event, lineups, rubbers played one
at a time, a tie decided at the wins needed with the rest unplayed, and team group tables."""

import pytest

from competitions import drawing, ties
from competitions.models import Entry, Match, Rubber

from .helpers import logged_in, make_user
from .test_draws import draw_url
from .test_entries import enter
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db
WIN = [(11, 5), (11, 7), (11, 9)]
LOSS = [(5, 11), (7, 11), (9, 11)]


@pytest.fixture
def cup(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, name="Teams", kind="team", format="round_robin")
    return do(staff, tournament, "publish")


def team(staff, cup, event, name: str, size=3) -> tuple[dict, list]:
    """A team entry and its players, the first being the captain."""
    players = [make_user(f"{name.lower()}{n}@example.com", display_name=f"{name} {n}") for n in range(size)]
    entry = enter(
        staff,
        cup,
        event,
        player_ids=[str(p.id) for p in players],
        team_name=name,
        captain_id=str(players[0].id),
    )
    return entry, players


@pytest.fixture
def tie(staff, cup):
    """A published two-team round robin: one tie between Tudor (side a or b as drawn) and Nyali."""
    event = cup["events"][0]
    tudor, tudor_players = team(staff, cup, event, "Tudor")
    nyali, nyali_players = team(staff, cup, event, "Nyali")
    assert staff.post(draw_url(cup, event, "preview"), {"rng_seed": 1}, format="json").status_code == 200
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200
    match = Match.objects.get(draw__event_id=event["id"])
    return {
        "cup": cup,
        "event": event,
        "match": match,
        "tudor": tudor,
        "tudor_players": tudor_players,
        "nyali": nyali,
        "nyali_players": nyali_players,
    }


def match_url(tie, action="") -> str:
    return url(tie["cup"], event=tie["event"]) + f"matches/{tie['match'].id}/" + action


def picks(players, order=((0,), (1,), (0, 1), (2,), (1,))) -> list[list[str]]:
    """A lineup for the default tie: singles, singles, doubles, singles, singles."""
    return [[str(players[i].id) for i in rubber] for rubber in order]


def hand_in(client, tie, which: str, lineup=None, expect=200) -> dict:
    body = {"entry_id": tie[which]["id"], "picks": lineup or picks(tie[f"{which}_players"])}
    response = client.post(match_url(tie, "lineup/"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def begin(staff, tie) -> list[Rubber]:
    hand_in(staff, tie, "tudor")
    hand_in(staff, tie, "nyali")
    return list(Rubber.objects.filter(match=tie["match"]))


def decide(rubber: Rubber, tie, winner: str, **how) -> None:
    """`winner` is "tudor" or "nyali"; without games the winner takes it 3-0."""
    entry = Entry.objects.get(pk=tie[winner]["id"])
    if "outcome" not in how and "games" not in how:
        how["games"] = WIN if entry.id == rubber.match.entry_a_id else LOSS
    ties.record_rubber(rubber, entry, **how)


def test_a_team_event_has_a_tie_format(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    events = add_event(staff, tournament, name="Teams", kind="team")["events"]
    assert (events[0]["tie_rubbers"], events[0]["tie_wins_needed"]) == (
        ["singles", "singles", "doubles", "singles", "singles"],
        3,
    )
    events = add_event(
        staff, tournament, name="Short", kind="team", tie_rubbers=["singles", "doubles", "singles"]
    )["events"]
    assert (events[1]["tie_rubbers"], events[1]["tie_wins_needed"]) == (["singles", "doubles", "singles"], 2)
    singles = add_event(staff, tournament, name="Singles", tie_rubbers=["singles"])["events"][2]
    assert (singles["tie_rubbers"], singles["tie_wins_needed"]) == ([], None)

    def refused(**body):
        response = staff.post(
            url(tournament, "events"),
            {"name": "Bad", "kind": "team", "format": "knockout", **body},
            format="json",
        )
        assert response.status_code == 400, response.json()
        return response.json()["fields"]

    # More wins than half the rubbers (rounded up) could leave a tie level with nothing left to play.
    assert "tie_wins_needed" in refused(tie_rubbers=["singles"] * 5, tie_wins_needed=4)
    assert "tie_wins_needed" in refused(tie_rubbers=["singles"] * 4, tie_wins_needed=3)
    assert "tie_wins_needed" in refused(tie_rubbers=["singles"] * 3, tie_wins_needed=0)
    four = add_event(staff, tournament, name="Four", kind="team", tie_rubbers=["singles"] * 4)["events"][3]
    assert four["tie_wins_needed"] == 2
    assert "tie_rubbers" in refused(tie_rubbers=["singles", "mixed"])
    assert "tie_rubbers" in refused(tie_rubbers=["singles"] * 10)

    # Changing the rubbers without saying how many wins takes the majority of the new number.
    changed = staff.patch(
        url(tournament, event=events[1]), {"tie_rubbers": ["singles"] * 5}, format="json"
    ).json()["events"][1]
    assert changed["tie_wins_needed"] == 3
    # The tie format is part of the structure: frozen once the event has started.
    do(staff, tournament, "publish")
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=events[0])
    frozen = staff.patch(url(tournament, event=events[0]), {"tie_wins_needed": 2}, format="json")
    assert (frozen.status_code, frozen.json()["code"]) == (409, "structure_frozen")


def test_invalid_lineups_are_refused(staff, tie):
    tudor, nyali = tie["tudor_players"], tie["nyali_players"]

    def refused(lineup, which="tudor") -> str:
        body = hand_in(staff, tie, which, lineup, expect=400)
        assert body["code"] == "invalid_lineup"
        return body["message"]

    assert "5 rubbers" in refused(picks(tudor)[:4])
    assert "one player" in refused(picks(tudor, ((0, 1), (1,), (0, 1), (2,), (1,))))
    assert "two players" in refused(picks(tudor, ((0,), (1,), (0,), (2,), (1,))))
    # A player from the other team, and somebody in no team at all.
    stranger = make_user("stranger@example.com")
    assert "roster" in refused([[str(nyali[0].id)], *picks(tudor)[1:]])
    assert "roster" in refused([[str(stranger.id)], *picks(tudor)[1:]])
    # The same player twice in a doubles is refused before it reaches the roster check.
    twice = staff.post(
        match_url(tie, "lineup/"),
        {
            "entry_id": tie["tudor"]["id"],
            "picks": [*picks(tudor)[:2], [str(tudor[0].id)] * 2, *picks(tudor)[3:]],
        },
        format="json",
    )
    assert twice.status_code == 400 and "different people" in twice.json()["message"]
    assert not tie["match"].lineups.exists()

    # A valid lineup may use a player in several rubbers.
    shown = hand_in(staff, tie, "tudor", picks(tudor, ((0,), (0,), (0, 1), (0,), (1,))))
    assert shown["tie"]["begun"] is False


def test_only_the_captain_or_staff_hand_in_a_lineup_and_it_stays_the_teams_own(staff, tie):
    tudor, nyali = tie["tudor_players"], tie["nyali_players"]
    side = "a" if str(tie["match"].entry_a_id) == tie["tudor"]["id"] else "b"
    other = "b" if side == "a" else "a"
    captain, teammate, rival = logged_in(tudor[0]), logged_in(tudor[1]), logged_in(nyali[0])
    outsider = logged_in(make_user("outsider@example.com"))

    before = captain.get(match_url(tie)).json()["tie"]
    assert (before["wins_needed"], before["begun"], before["score"], before["rubbers"]) == (
        3,
        False,
        [0, 0],
        [],
    )
    assert before[side] == {"submitted": False, "submitted_at": None, "can_submit": True, "picks": None}
    assert before[other]["can_submit"] is False  # not the other team's captain

    for client in (teammate, rival, outsider):
        refused = client.post(
            match_url(tie, "lineup/"), {"entry_id": tie["tudor"]["id"], "picks": picks(tudor)}, format="json"
        )
        assert (refused.status_code, refused.json()["code"]) == (403, "permission_denied")
    # A captain can't hand in the other team's lineup either.
    assert hand_in(captain, tie, "nyali", picks(nyali), expect=403)["code"] == "permission_denied"

    mine = hand_in(captain, tie, "tudor")["tie"][side]
    assert mine["submitted"] is True and mine["picks"] == picks(tudor) and mine["can_submit"] is True
    assert teammate.get(match_url(tie)).json()["tie"][side]["picks"] == picks(tudor)
    for client in (rival, outsider):
        seen = client.get(match_url(tie)).json()["tie"][side]
        assert (seen["submitted"], seen["picks"]) == (True, None)
    assert staff.get(match_url(tie)).json()["tie"][side]["picks"] == picks(tudor)

    # The captain may change it until the other lineup is in.
    changed = picks(tudor, ((2,), (1,), (0, 2), (0,), (1,)))
    assert hand_in(captain, tie, "tudor", changed)["tie"][side]["picks"] == changed
    begun = hand_in(rival, tie, "nyali")["tie"]
    assert begun["begun"] is True and len(begun["rubbers"]) == 5
    assert begun["a"]["picks"] is None and begun["a"]["can_submit"] is False
    first = begun["rubbers"][0]
    assert first["kind"] == "singles" and first["status"] == "scheduled"
    assert [p["display_name"] for p in first[f"{side}_players"]] == ["Tudor 2"]
    assert [p["display_name"] for p in begun["rubbers"][2][f"{side}_players"]] == ["Tudor 0", "Tudor 2"]
    assert hand_in(captain, tie, "tudor", expect=409)["code"] == "tie_begun"


def test_rubbers_are_played_one_at_a_time_and_the_wins_needed_decide_the_tie(staff, tie):
    rubbers = begin(staff, tie)
    with pytest.raises(Exception, match="Rubber 1 is played first"):
        decide(rubbers[1], tie, "tudor")
    decide(rubbers[0], tie, "tudor")
    with pytest.raises(Exception, match="already decided"):
        decide(rubbers[0], tie, "nyali")
    with pytest.raises(Exception, match="don't fit"):
        decide(rubbers[1], tie, "nyali", games=[(11, 5)])
    decide(rubbers[1], tie, "nyali")
    shown = staff.get(match_url(tie)).json()
    side = "a" if str(tie["match"].entry_a_id) == tie["tudor"]["id"] else "b"
    assert shown["tie"]["score"] == ([1, 1])
    assert (shown["status"], shown["tie_score"], shown["tie"]["can_reset"]) == ("scheduled", [1, 1], False)

    decide(rubbers[2], tie, "tudor")
    decide(rubbers[3], tie, "tudor")  # the third win
    match = Match.objects.get(pk=tie["match"].pk)
    assert (match.status, str(match.winner_id), match.outcome, match.games) == (
        "completed",
        tie["tudor"]["id"],
        "played",
        [],
    )
    surplus = Rubber.objects.get(match=match, position=5)
    assert (surplus.status, surplus.winner, surplus.games) == ("not_played", None, [])
    with pytest.raises(Exception, match="already decided or was not needed"):
        decide(surplus, tie, "nyali")
    shown = staff.get(match_url(tie)).json()
    assert shown["tie"]["score"] == ([3, 1] if side == "a" else [1, 3])
    assert [r["status"] for r in shown["tie"]["rubbers"]] == ["completed"] * 4 + ["not_played"]
    assert shown["winner_id"] == tie["tudor"]["id"]
    # Nothing about a decided tie can be handed in or reset.
    assert hand_in(staff, tie, "tudor", expect=409)["code"] == "match_decided"
    assert staff.post(match_url(tie, "lineup/reset/"), {}, format="json").status_code == 409


def test_staff_can_send_both_teams_back_until_a_rubber_is_decided(staff, tie):
    rubbers = begin(staff, tie)
    captain = logged_in(tie["tudor_players"][0])
    assert captain.post(match_url(tie, "lineup/reset/"), {}, format="json").status_code == 403
    reset = staff.post(match_url(tie, "lineup/reset/"), {}, format="json")
    assert reset.status_code == 200 and reset.json()["tie"]["begun"] is False
    assert not tie["match"].lineups.exists() and not tie["match"].rubbers.exists()
    rubbers = begin(staff, tie)
    decide(rubbers[0], tie, "nyali")
    refused = staff.post(match_url(tie, "lineup/reset/"), {}, format="json")
    assert (refused.status_code, refused.json()["code"]) == (409, "tie_under_way")


def test_a_tie_is_not_decided_like_a_singles_match_and_can_be_awarded_unplayed(staff, tie):
    match = tie["match"]
    tudor = Entry.objects.get(pk=tie["tudor"]["id"])
    with pytest.raises(Exception, match="decided by its rubbers"):
        drawing.record_result(match, tudor, games=[(11, 5)] * 3)
    with pytest.raises(Exception, match="decided by its rubbers"):
        drawing.record_result(match, tudor)  # no rubbers won
    rubbers = begin(staff, tie)
    drawing.record_result(match, tudor, outcome="walkover")
    assert {r.status for r in Rubber.objects.filter(match=match)} == {"not_played"}
    assert len(rubbers) == 5
    table = staff.get(url(tie["cup"], event=tie["event"]) + "standings/").json()["groups"][0]
    assert [(r["entry"]["title"], r["match_points"]) for r in table["rows"]] == [("Tudor", 2), ("Nyali", 0)]
    # Credited as the wins needed in straight games: 3 rubbers x 3 games at 11-0.
    assert (table["rows"][0]["games_won"], table["rows"][0]["points_won"]) == (9, 99)


def test_lineups_belong_to_ties_of_a_published_team_draw(staff, cup):
    singles_cup = add_event(staff, cup, name="Singles")
    event = singles_cup["events"][1]
    entries = [
        enter(staff, singles_cup, event, player_ids=[str(make_user(f"s{n}@example.com").id)])
        for n in range(2)
    ]
    staff.post(draw_url(singles_cup, event, "preview"), {}, format="json")
    staff.post(draw_url(singles_cup, event, "publish"), {}, format="json")
    match = Match.objects.get(draw__event_id=event["id"])
    path = url(singles_cup, event=event) + f"matches/{match.id}/lineup/"
    refused = staff.post(
        path, {"entry_id": entries[0]["id"], "picks": [[entries[0]["players"][0]["id"]]]}, format="json"
    )
    assert (refused.status_code, refused.json()["code"]) == (409, "not_a_tie")


def test_a_team_group_is_ranked_on_individual_matches_before_games(staff, cup):
    """Three teams each win one tie (F-ST3 shape for teams): level on match points, they are separated
    by the rubbers won and lost between them, 3.7.5.2."""
    event = cup["events"][0]
    teams = {name: team(staff, cup, event, name) for name in ("Tudor", "Nyali", "Bamburi")}
    assert staff.post(draw_url(cup, event, "preview"), {"rng_seed": 2}, format="json").status_code == 200
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200
    by_pair = {
        frozenset((str(m.entry_a_id), str(m.entry_b_id))): m
        for m in Match.objects.filter(draw__event_id=event["id"])
    }

    def play(winner: str, loser: str, sequence: str) -> None:
        """`sequence` says who takes each rubber in turn: W for the tie's winner, L for its loser."""
        match = by_pair[frozenset((teams[winner][0]["id"], teams[loser][0]["id"]))]
        for name in (winner, loser):
            body = {"entry_id": teams[name][0]["id"], "picks": picks(teams[name][1])}
            path = url(cup, event=event) + f"matches/{match.id}/lineup/"
            assert staff.post(path, body, format="json").status_code == 200
        for letter in sequence:
            rubber = Rubber.objects.filter(match=match, status="scheduled").order_by("position").first()
            entry = Entry.objects.get(pk=teams[winner if letter == "W" else loser][0]["id"])
            ties.record_rubber(rubber, entry, games=WIN if entry.id == match.entry_a_id else LOSS)

    play("Tudor", "Nyali", "WWW")  # 3-0
    play("Nyali", "Bamburi", "WLWW")  # 3-1
    play("Bamburi", "Tudor", "WLWLW")  # 3-2
    table = staff.get(url(cup, event=event) + "standings/").json()["groups"][0]
    assert table["complete"] is True
    # Rubbers between them: Tudor 5/3, Bamburi 4/5, Nyali 3/4.
    assert [r["entry"]["title"] for r in table["rows"]] == ["Tudor", "Bamburi", "Nyali"]
    assert [(s["measure"], s["value"]) for s in table["rows"][0]["tie_break"]] == [
        ("match_points", "3"),
        ("rubbers", "5/3"),
    ]
    # The table's games are those of the rubbers played: Tudor won 5 rubbers 3-0 and lost 3 by 0-3.
    assert (table["rows"][0]["games_won"], table["rows"][0]["games_lost"]) == (15, 9)


def test_the_tie_format_cannot_change_under_a_lineup(staff, tie):
    hand_in(staff, tie, "tudor")
    for change in ({"tie_rubbers": ["singles"] * 7}, {"tie_wins_needed": 2}):
        refused = staff.patch(url(tie["cup"], event=tie["event"]), change, format="json")
        assert (refused.status_code, refused.json()["code"]) == (409, "lineups_in"), change
    # How many games the rubbers are played over doesn't change who plays them (TASK-158).
    assert staff.patch(url(tie["cup"], event=tie["event"]), {"best_of": 3}, format="json").status_code == 200
    # Other details still change, and so does the format once the lineups are cleared.
    assert (
        staff.patch(url(tie["cup"], event=tie["event"]), {"rest_minutes": 5}, format="json").status_code
        == 200
    )
    hand_in(staff, tie, "nyali")
    assert staff.post(match_url(tie, "lineup/reset/"), {}, format="json").status_code == 200
    changed = staff.patch(
        url(tie["cup"], event=tie["event"]), {"tie_rubbers": ["singles"] * 3}, format="json"
    )
    assert changed.status_code == 200
    assert "3 rubbers" in hand_in(staff, tie, "tudor", expect=400)["message"]  # the old five no longer fit


def test_a_tie_a_team_cannot_finish_is_awarded_and_completed_in_the_winners_favour(staff, tie):
    rubbers = begin(staff, tie)
    match = tie["match"]
    tudor = Entry.objects.get(pk=tie["tudor"]["id"])
    with pytest.raises(Exception, match="decided by its rubbers"):
        drawing.record_result(match, tudor, outcome="retired")  # nothing decided yet: that is a walkover
    decide(rubbers[0], tie, "nyali")
    decide(rubbers[1], tie, "tudor", outcome="walkover")
    with pytest.raises(Exception, match="decided by its rubbers"):
        drawing.record_result(match, tudor, outcome="walkover")
    drawing.record_result(match, tudor, outcome="retired")
    assert [r.status for r in Rubber.objects.filter(match=match)] == ["completed"] * 2 + ["not_played"] * 3
    table = staff.get(url(tie["cup"], event=tie["event"]) + "standings/").json()["groups"][0]
    first, second = table["rows"]
    assert [(r["entry"]["title"], r["match_points"]) for r in table["rows"]] == [("Tudor", 2), ("Nyali", 0)]
    # Tudor: lost a rubber 0-3, won one by walkover (3 games to nil) and is credited two more the same way.
    assert (first["games_won"], first["games_lost"]) == (9, 3)
    assert (second["games_won"], second["games_lost"]) == (3, 9)
