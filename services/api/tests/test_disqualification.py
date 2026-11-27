"""Disqualification and the referee (release plan 2.0, decision D5): only the referee awards or takes away
a disqualification; it records what was played before it, rates nothing, and the loser scores nothing."""

from unittest import mock

import pytest

from competitions import drawing, recap, standings
from competitions.models import Match
from competitions.standings import DISQUALIFIED, Result, rank
from organizations.permissions import Permission
from outbox import service as outbox
from ratings.models import RatingEvent
from realtime import broadcast
from reservations import service as reservations

from .helpers import logged_in, make_user
from .test_official_results import correct, enter, fresh, hall, knockout  # noqa: F401
from .test_reservations import person, send, started, tables
from .test_roles import add_member


def staff_member(club, email, *roles):
    user = make_user(email)
    add_member(club, user, *roles)
    return logged_in(user)


def test_the_referee_template_holds_the_referee_permission(club):
    referee = club.roles.get(key="referee")
    assert set(referee.permissions) == {"results.referee", "results.manage", "scoring.assigned"}
    assert Permission.RESULTS_REFEREE not in club.roles.get(key="captain").permissions


def test_only_the_referee_awards_a_disqualification(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    captain = staff_member(club, "captain@example.com", "captain")
    refused = enter(captain, game, first, first.entry_a, expect=403, outcome="disqualified")
    assert refused["code"] == "referee_only"
    assert fresh(first).status == Match.Status.SCHEDULED
    # The referee may, with no other role: the results desk is theirs too.
    referee = staff_member(club, "referee@example.com", "referee")
    enter(referee, game, first, first.entry_a, outcome="disqualified", games=[[11, 7], [4, 3]])
    decided = fresh(first)
    assert (decided.status, decided.outcome, decided.winner_id) == (
        "completed",
        "disqualified",
        first.entry_a_id,
    )
    assert decided.games == [[11, 7], [4, 3]]
    # Before play, with nothing played at all; the club admin holds every permission.
    enter(staff, game, second, second.entry_b, outcome="disqualified")
    assert fresh(second).outcome == "disqualified" and fresh(second).games == []
    # And the winners move on as after any result.
    assert {fresh(game["final"]).entry_a_id, fresh(game["final"]).entry_b_id} == {
        first.entry_a_id,
        second.entry_b_id,
    }


def test_a_disqualification_cannot_claim_a_finished_match(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    won = [[11, 1], [11, 2], [11, 3]]
    assert enter(staff, game, first, first.entry_a, expect=400, outcome="disqualified", games=won)
    assert fresh(first).status == Match.Status.SCHEDULED


def test_only_the_referee_takes_a_disqualification_away(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    enter(staff, game, first, first.entry_a, outcome="disqualified")
    captain = staff_member(club, "captain@example.com", "captain")
    refused = correct(captain, game, first, first.entry_a, expect=403, outcome="walkover")
    assert refused["code"] == "referee_only"
    correct(staff, game, first, first.entry_a, outcome="walkover")
    assert fresh(first).outcome == "walkover"


def test_a_disqualification_changes_no_rating(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    enter(staff, game, first, first.entry_a, outcome="disqualified", games=[[11, 5]])
    while outbox.work():
        pass
    assert not RatingEvent.objects.exists()


def test_in_a_group_the_disqualified_player_scores_nothing_and_the_game_in_progress_goes_to_the_winner():
    dq = Result("X", "Y", DISQUALIFIED, games=((11, 9), (4, 2)))
    assert standings.credited_games(dq) == [(11, 9), (11, 2), (11, 0)]
    rows = {row.member: row for row in rank(["X", "Y"], [dq])}
    assert (rows["X"].match_points, rows["Y"].match_points) == (2, 0)


@pytest.mark.parametrize("topic", ["scores", "results", "board"])
def test_the_board_is_a_live_topic_beside_scores_and_results(topic):
    with mock.patch.object(broadcast.transaction, "on_commit") as later:
        broadcast.tournament_changed("t-1", topic)
    later.assert_called_once()
    with pytest.raises(ValueError):
        broadcast.tournament_changed("t-1", "elsewhere")


def test_the_match_page_offers_the_result_desk_to_the_referee_and_not_to_staff_once_disqualified(
    staff,
    club,
    hall,  # noqa: F811
):
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    page = f"/api/v1/tournaments/{game['cup']['id']}/events/{game['event']['id']}/matches/{first.id}/"
    captain = staff_member(club, "captain@example.com", "captain")
    referee = staff_member(club, "referee@example.com", "referee")
    assert captain.get(page).json()["can_record_result"] and referee.get(page).json()["can_record_result"]
    enter(referee, game, first, first.entry_a, outcome="disqualified")
    assert not captain.get(page).json()["can_record_result"]
    assert referee.get(page).json()["can_record_result"]


def test_a_disqualification_before_play_is_no_play_so_nobody_rests_after_it(staff, club, hall):  # noqa: F811
    one, _ = tables(hall)
    first = started(staff, club, hall, [["Amina"], ["Brian"]])
    send(staff, first, one)
    match = first["match"]
    drawing.record_result(match, match.entry_a, outcome="disqualified")
    assert reservations.rest_until(person("Amina"), match.draw.event) is None
    second = started(staff, club, hall, [["Chege"], ["Daudi"]], tournament="Veterans Cup")
    send(staff, second, one)
    part_way = second["match"]
    drawing.record_result(part_way, part_way.entry_a, outcome="disqualified", games=[[11, 4], [2, 1]])
    assert reservations.rest_until(person("Chege"), part_way.draw.event) is not None


def test_the_result_card_marks_a_disqualification_and_counts_only_finished_games():
    shown = {
        "tournament_name": "Coast Open", "event_name": "Men's singles", "side_a": "Amina", "side_b": "Brian",
        "games": [[11, 7], [4, 3]], "winner_side": "a", "official": True, "outcome": "disqualified",
    }  # fmt: skip
    rows = recap.card_rows(shown)
    assert [(row.text, row.aside) for row in rows[:2]] == [("Amina", "1"), ("Brian", "0")]  # 4-3 isn't won
    assert "4-3" in rows[2].text and rows[3].text == "Amina wins (DQ)"
    assert recap.card_png(shown).startswith(b"\x89PNG")
