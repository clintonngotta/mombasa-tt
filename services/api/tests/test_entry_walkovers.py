"""A player who doesn't turn up loses every match they have left in the event by walkover, in one go
(REQ-043, user request 2026-11-28), instead of the referee giving each walkover on its own."""

import pytest

from competitions.models import Match, MatchDayLog, OfficialResult
from outbox import service as outbox
from ratings.models import RatingEvent
from scoring.models import Scorecard

from .helpers import logged_in, make_user
from .test_disqualification import staff_member
from .test_official_results import GAMES, enter, fresh, hall, knockout  # noqa: F401
from .test_reservations import started
from .test_roles import add_member
from .test_tournaments import url

pytestmark = pytest.mark.django_db

NO_SHOW = "No-show after the grace period"


def walk_over(client, game, entry, expect=200, **body) -> dict:
    path = url(game["cup"], event=game["event"]) + f"entries/{entry.id}/walkovers/"
    response = client.post(path, body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def group_of_four(staff, club, hall) -> tuple[dict, list[Match]]:  # noqa: F811
    game = started(
        staff,
        club,
        hall,
        [["Amina"], ["Brian"], ["Chege"], ["Daudi"]],
        format="round_robin",
    )
    return game, list(Match.objects.filter(draw__event_id=game["event"]["id"], stage="group"))


def entry_named(matches: list[Match], name: str):
    return next(
        side
        for match in matches
        for side in (match.entry_a, match.entry_b)
        if side and side.players.filter(user__display_name=name).exists()
    )


def test_the_referee_gives_every_match_of_a_no_show_to_their_opponents(staff, club, hall):  # noqa: F811
    game, matches = group_of_four(staff, club, hall)
    amina = entry_named(matches, "Amina")
    hers = [m for m in matches if amina.id in (m.entry_a_id, m.entry_b_id)]
    assert len(hers) == 3
    referee = staff_member(club, "referee@example.com", "referee")

    shown = walk_over(referee, game, amina, reason=NO_SHOW)

    assert sorted(item["match_id"] for item in shown["awarded"]) == sorted(str(m.id) for m in hers)
    assert shown["skipped"] == []
    assert {item["label"] for item in shown["awarded"]} == {"Group A"}
    for match in map(fresh, hers):
        assert (match.status, match.outcome, match.games) == ("completed", "walkover", [])
        assert match.winner_id != amina.id
        assert OfficialResult.objects.get(match=match, current=True).reason == NO_SHOW
        log = MatchDayLog.objects.get(action="result_entered", match=match)
        assert "walkover" in log.summary and log.reason == NO_SHOW
    # The other matches of the group are still to be played.
    others = [fresh(m) for m in matches if m not in hers]
    assert others and all(m.status == Match.Status.SCHEDULED for m in others)
    while outbox.work():
        pass
    assert not RatingEvent.objects.exists()
    # Sent again, nothing is left to give.
    assert walk_over(referee, game, amina, reason=NO_SHOW) == {"awarded": [], "skipped": []}


def test_matches_already_decided_or_begun_or_without_an_opponent_are_left_alone(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    # The player won the semi-final; the final waits for the other semi-final.
    enter(staff, game, first, first.entry_a, games=GAMES)
    shown = walk_over(staff, game, first.entry_a, reason=NO_SHOW)
    assert shown["awarded"] == []
    assert [(s["match_id"], s["code"]) for s in shown["skipped"]] == [
        (str(game["final"].id), "match_not_ready")
    ]
    assert fresh(first).outcome == "played"

    # Once the umpire has begun scoring, the referee's one-go walkover leaves the match to them.
    Scorecard.objects.create(match=second, revision=1)
    shown = walk_over(staff, game, second.entry_a, reason=NO_SHOW)
    assert [(s["match_id"], s["code"]) for s in shown["skipped"]] == [(str(second.id), "already_started")]
    assert fresh(second).status == Match.Status.SCHEDULED


def test_only_the_referee_walks_a_player_over(staff, club, hall):  # noqa: F811
    game, matches = group_of_four(staff, club, hall)
    amina = entry_named(matches, "Amina")
    captain = staff_member(club, "captain@example.com", "captain")
    assert walk_over(captain, game, amina, expect=403, reason=NO_SHOW)["code"] == "referee_only"
    outsider = logged_in(make_user("outsider@example.com"))
    # Like the results desk: refused before the entry is even looked up.
    assert walk_over(outsider, game, amina, expect=403)["code"] == "permission_denied"
    assert all(fresh(m).status == Match.Status.SCHEDULED for m in matches)


def test_an_entry_of_another_event_is_not_found(staff, club, hall):  # noqa: F811
    game, _ = group_of_four(staff, club, hall)
    other = knockout(staff, club, hall, tournament="Mombasa Masters")
    walk_over(staff, game, other["semis"][0].entry_a, expect=404)


def test_a_referee_never_decides_a_match_they_play_in(staff, club, hall):  # noqa: F811
    game, matches = group_of_four(staff, club, hall)
    amina = entry_named(matches, "Amina")
    # Amina is the host's referee as well as a player.
    player = amina.players.get().user
    add_member(club, player, "referee")
    referee = logged_in(player)
    hers = next(m for m in matches if amina.id in (m.entry_a_id, m.entry_b_id))
    page = url(game["cup"], event=game["event"]) + f"matches/{hers.id}/"
    shown = referee.get(page).json()
    assert not shown["can_record_result"] and not shown["can_award_walkover"]
    refused = enter(referee, game, hers, amina, expect=403, outcome="walkover")
    assert refused["code"] == "plays_in_match"
    # Walking over an opponent of theirs, or themselves, leaves their own matches alone.
    opponent = hers.entry_b if hers.entry_a_id == amina.id else hers.entry_a
    shown = walk_over(referee, game, opponent, reason=NO_SHOW)
    assert (str(hers.id), "plays_in_match") in [(s["match_id"], s["code"]) for s in shown["skipped"]]
    assert len(shown["awarded"]) == 2
    assert fresh(hers).status == Match.Status.SCHEDULED
