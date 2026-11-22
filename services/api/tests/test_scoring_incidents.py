"""Scoring incidents on the server (REQ-043, EVAL-043, TASK-083): cards and penalty points, adviser cards,
time-outs, suspensions, expedite, retirement and disqualification as the umpire records them; only the
referee disqualifies; a retirement or disqualification keeps the points played and rates nothing; a team
tie carries its warnings into later rubbers."""

import pytest

from competitions.models import Match, OfficialResult, Rubber
from outbox import service as outbox
from ratings.models import RatingEvent
from scoring.models import MatchIncident, Scorecard

from .helpers import logged_in, make_user
from .test_roles import add_member
from .test_ties import begin, cup, tie  # noqa: F401
from .test_umpire_scoring import START, Deck, assign, final, match_url, point, scorers  # noqa: F401

pytestmark = pytest.mark.django_db


def card(player: str, reason: str = "bad_behaviour", note: str | None = None) -> dict:
    event = {"type": "card", "player": player, "reason": reason}
    if note is not None:
        event["note"] = note
    return event


def umpire_with(club, email: str, *roles):
    user = make_user(email, display_name=email.split("@")[0].title())
    add_member(club, user, *roles)
    return user


def deck_for(staff, club, game, user) -> Deck:
    assign(staff, game, user)
    client = logged_in(user)
    return Deck(client, client.get(match_url(game)).json()["scoring"]["scorecard_id"])


def test_the_card_ladder_is_recorded_with_its_penalty_points_and_undone_with_the_event(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    a_player = final["match"].entry_a.players.get().user
    shown = deck.send(START, card("a1", note="Swore at the umpire"), card("a1", "racket_abuse"), card("a1"))
    assert shown["accepted"] == 4
    sheet = deck.client.get(deck.path).json()
    assert sheet["state"]["points"] == [0, 3] and sheet["state"]["offences"]["a1"] == 3
    assert [(i["card"], i["penalty_points"], i["reason"]) for i in sheet["incidents"]] == [
        ("yellow", 0, "bad_behaviour"),
        ("yellow_red", 1, "racket_abuse"),
        ("yellow_red", 2, "bad_behaviour"),
    ]
    assert {i["player_name"] for i in sheet["incidents"]} == {a_player.display_name}
    assert sheet["incidents"][0]["note"] == "Swore at the umpire"
    # The match page shows the cards to everybody, never the umpire's note.
    public = staff.get(match_url(final)).json()["scoring"]["incidents"]
    assert len(public) == 3 and all("note" not in i for i in public)
    # A fourth offence is the referee's; an undo takes the last card back.
    assert deck.send(card("a1"))["refused"]["code"] == "refer_to_referee"
    deck.sequence -= 1
    deck.send({"type": "undo"})
    assert MatchIncident.objects.filter(kind="card").count() == 2
    assert deck.send(card("a1", note="x" * 201))["refused"]["code"] == "invalid_note"


def test_only_a_referee_umpire_disqualifies_and_the_result_keeps_the_points_played(staff, club, final):  # noqa: F811
    plain = umpire_with(club, "zuri@example.com", scorers(club))
    deck = deck_for(staff, club, final, plain)
    deck.send(START, *[point("a")] * 11, point("b"), point("b"))
    assert deck.client.get(deck.path).json()["can_disqualify"] is False
    assert deck.send({"type": "disqualify", "side": "b"})["refused"]["code"] == "referee_only"
    deck.sequence -= 1
    # The referee umpiring the match may: the match goes to side a with the points played.
    referee = umpire_with(club, "rhoda@example.com", "referee")
    deck = deck_for(staff, club, final, referee)
    assert deck.client.get(deck.path).json()["can_disqualify"] is True
    assert deck.send({"type": "disqualify", "side": "b"})["accepted"] == 1
    deck.confirm()
    match = Match.objects.get(pk=final["match"].pk)
    assert (match.outcome, match.winner_id, match.games) == (
        "disqualified",
        match.entry_a_id,
        [[11, 0], [0, 2]],
    )
    assert OfficialResult.objects.get(match=match, current=True).outcome == "disqualified"
    while outbox.work():
        pass
    assert not RatingEvent.objects.exists()


def test_a_player_who_cannot_resume_after_a_suspension_retires(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    deck.send(START, point("a"), {"type": "suspension", "side": "a"})
    assert deck.send(point("b"))["refused"]["code"] == "suspended"
    deck.sequence -= 1
    deck.send({"type": "retire", "side": "a"})
    deck.confirm()
    match = Match.objects.get(pk=final["match"].pk)
    assert (match.outcome, match.winner_id, match.games) == ("retired", match.entry_b_id, [[1, 0]])
    kinds = list(MatchIncident.objects.values_list("kind", flat=True))
    assert kinds == ["suspension", "retired"]


def test_time_outs_and_expedite_are_incidents_too(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    deck.send(
        START, point("a"), {"type": "timeout", "side": "b"}, {"type": "timeout_end"}, {"type": "expedite"}
    )
    deck.send({"type": "adviser_card", "side": "a", "reason": "illegal_advice"})
    sheet = deck.client.get(deck.path).json()
    assert sheet["state"]["expedite"] is True and sheet["state"]["advisers"] == [1, 0]
    assert [i["kind"] for i in sheet["incidents"]] == ["timeout", "timeout_end", "expedite", "adviser_card"]
    assert sheet["incidents"][3]["card"] == "yellow"


def test_a_team_tie_carries_warnings_into_its_later_rubbers(staff, tie):  # noqa: F811
    from scoring import service

    first, second, *_ = begin(staff, tie)
    one = Scorecard.objects.create(rubber=first)
    one.state = {**one.state, "offences": {"a1": 2, "a2": 0, "b1": 0, "b2": 0}, "advisers": [0, 1]}
    one.save()
    player = service.players_of(one)["a"][0]
    later = [
        rubber for rubber in begin_rest(tie) if player in service.players_of(Scorecard(rubber=rubber))["a"]
    ]
    assert later, "the lineup plays the first rubber's player again"
    sheet = Scorecard.objects.create(rubber=later[0])
    config = service.config_of(sheet)
    slot = f"a{service.players_of(sheet)['a'].index(player) + 1}"
    assert config["carry"]["offences"][slot] == 2
    assert config["carry"]["advisers"] == [0, 1]
    # Nothing carried, nothing in the configuration.
    assert "carry" not in service.config_of(one)


def begin_rest(game) -> list[Rubber]:
    return list(Rubber.objects.filter(match=game["match"], position__gt=1).order_by("position"))


def test_a_retirement_part_way_through_a_game_is_confirmed_with_that_game_as_played(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    best_of = final["match"].draw.event.best_of
    won = best_of // 2  # one game short of the match, then a lead in the next
    deck.send(START, *[point("a")] * (11 * won), *[point("a")] * 6, point("b"), point("b"))
    deck.send({"type": "retire", "side": "b"})
    deck.confirm()
    match = Match.objects.get(pk=final["match"].pk)
    assert (match.outcome, match.winner_id) == ("retired", match.entry_a_id)
    assert match.games == [[11, 0]] * won + [[6, 2]]


def test_a_reason_on_an_event_that_takes_none_is_not_kept(staff, club, final):  # noqa: F811
    deck = deck_for(staff, club, final, umpire_with(club, "zuri@example.com", scorers(club)))
    shown = deck.send(START, point("a"), {"type": "timeout", "side": "a", "reason": "x" * 300})
    assert shown["accepted"] == 3
    assert MatchIncident.objects.get(kind="timeout").reason == ""
    assert Scorecard.objects.get(pk=deck.path.rstrip("/").split("/")[-1]).carry is None


def test_what_a_rubber_carries_in_is_fixed_once_it_is_scored(staff, tie):  # noqa: F811
    from scoring import service

    first, *_ = begin(staff, tie)
    one = Scorecard.objects.create(rubber=first)
    one.state = {**one.state, "advisers": [1, 0]}
    one.save()
    later = Scorecard.objects.create(rubber=begin_rest(tie)[0])
    assert service.config_of(later)["carry"]["advisers"] == [1, 0]
    # Scoring began with that carry; the earlier sheet struck out and re-scored doesn't change it.
    Scorecard.objects.filter(pk=later.pk).update(revision=1, carry=service.config_of(later)["carry"])
    one.state = {**one.state, "advisers": [0, 0]}
    one.save()
    later.refresh_from_db()
    assert service.config_of(later)["carry"]["advisers"] == [1, 0]
    assert "carry" not in service.config_of(later, with_carry=False)
