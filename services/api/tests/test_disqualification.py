"""Disqualification and the referee (release plan 2.0, decision D5): only the referee awards or takes away
a disqualification; it records what was played before it, rates nothing, and the loser scores nothing."""

from unittest import mock

import pytest

from competitions import standings
from competitions.models import Match
from competitions.standings import DISQUALIFIED, Result, rank
from organizations.permissions import Permission
from outbox import service as outbox
from ratings.models import RatingEvent
from realtime import broadcast

from .helpers import logged_in, make_user
from .test_official_results import correct, enter, fresh, hall, knockout  # noqa: F401
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
    # Competition staff who also hold the Referee role may.
    referee = staff_member(club, "referee@example.com", "captain", "referee")
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
