"""The umpire gives a walkover from the scoring deck (REQ-043, user request 2026-11-28).

Before the first point, the umpire of the match records that a side didn't play and why. Confirming it
makes the walkover official like any other result: no games, no rating, and a line in the match-day
log with the reason. No referee role is needed for it.
"""

import pytest

from competitions.models import EntryPlayer, Match, MatchDayLog, OfficialResult
from outbox import service as outbox
from ratings.models import RatingEvent
from scoring.models import MatchIncident

from .test_scoring_incidents import deck_for, umpire_with
from .test_ties import cup, tie  # noqa: F401
from .test_umpire_scoring import START, final, point, scorers  # noqa: F401

pytestmark = pytest.mark.django_db


def walkover(side: str, reason: str = "no_show", **more) -> dict:
    return {"type": "walkover", "side": side, "reason": reason, **more}


def test_an_umpire_who_is_no_referee_gives_a_walkover_and_confirms_it(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    assert deck.client.get(deck.path).json()["can_disqualify"] is False
    assert deck.send(walkover("b", note="Not at the table after 10 minutes"))["accepted"] == 1
    deck.confirm()

    match = Match.objects.get(pk=final["match"].pk)
    assert (match.outcome, match.winner_id, match.games) == ("walkover", match.entry_a_id, [])
    assert OfficialResult.objects.get(match=match, current=True).outcome == "walkover"
    incident = MatchIncident.objects.get()
    assert (incident.kind, incident.side, incident.reason) == ("walkover", "b", "no_show")
    log = MatchDayLog.objects.get(action="result_entered", match=match)
    assert "walkover" in log.summary
    assert log.reason == "No-show after the grace period: Not at the table after 10 minutes"
    while outbox.work():
        pass
    assert not RatingEvent.objects.exists()


def test_a_walkover_is_refused_once_the_match_has_started_or_without_a_known_reason(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    assert deck.send(walkover("a", "late"))["refused"]["code"] == "invalid_walkover"
    deck.sequence -= 1
    deck.send(START, point("a"))
    assert deck.send(walkover("b"))["refused"]["code"] == "already_started"
    deck.sequence -= 1
    assert Match.objects.get(pk=final["match"].pk).status == Match.Status.SCHEDULED


def test_an_undone_walkover_leaves_the_match_to_be_played(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    deck.send(walkover("a", "injury"), {"type": "undo"})
    assert not MatchIncident.objects.exists()
    assert deck.confirm(expect=409)["code"] == "match_not_finished"
    deck.send(START, *[point("a")] * 22)
    deck.confirm()
    assert Match.objects.get(pk=final["match"].pk).outcome == "played"
    assert not MatchDayLog.objects.filter(action="result_entered").exists()


def test_an_umpire_who_turns_out_to_play_in_the_match_loses_the_sheet(staff, club, final):  # noqa: F811
    umpire = umpire_with(club, "zuri@example.com", scorers(club))
    deck = deck_for(staff, club, final, umpire)
    assert deck.client.get(deck.path).status_code == 200
    # Put on one of the sides afterwards: an umpire never scores, or gives a walkover in, their own match.
    entry = final["match"].entry_a
    EntryPlayer.objects.create(entry=entry, event_id=entry.event_id, user=umpire)
    assert deck.client.get(deck.path).status_code == 404
    deck.send(walkover("b"), expect=404)
    assert Match.objects.get(pk=final["match"].pk).status == Match.Status.SCHEDULED
