"""An umpire takes the match recommended for their table next (user request, 2026-11-28).

After confirming their match, the umpire sees what follows on their table (TASK-128). If nobody umpires
it yet they can claim it: they become its umpire and, while it is still in the queue, it waits for their
table. Everything that guards assigning an umpire still applies.
"""

import pytest

from competitions.models import Match, MatchDayLog
from scoring.models import Scorecard

from .helpers import logged_in, make_user
from .test_reservations import person, send, started, tables
from .test_roles import add_member
from .test_table_umpires import add_umpire, eight, hall, round_one, umpire_of  # noqa: F401
from .test_umpire_scoring import START, Deck, assign, point

pytestmark = pytest.mark.django_db


def finished(staff, club, hall, name="Zuri Next"):  # noqa: F811
    """A knockout of eight: the first match on Table 1, scored to the end by an umpire staff chose (no
    table umpire, so nothing gives them the next match by itself). The deck is not confirmed yet."""
    game = started(staff, club, hall, eight("E"), best_of=3)
    one, _ = tables(hall)
    first = round_one(game)[0]
    zuri = person(name)
    add_member(club, zuri)
    add_umpire(staff, game, zuri)
    send(staff, {**game, "match": first}, one)
    assign(staff, {**game, "match": first}, zuri)
    deck = Deck(logged_in(zuri), Scorecard.objects.get(match=first).id)
    deck.send(START, *[point("a")] * 22)
    return game, zuri, deck, one


def paths(deck) -> tuple[str, str]:
    base = f"/api/v1/scorecards/{deck.path.split('/')[-2]}/next/"
    return base, base + "claim/"


def test_the_umpire_takes_the_recommended_match_and_it_waits_for_their_table(staff, club, hall):  # noqa: F811
    game, zuri, deck, one = finished(staff, club, hall)
    shown, claim = paths(deck)
    client = logged_in(zuri)
    assert client.post(claim).json()["code"] == "not_confirmed"
    deck.confirm()
    told = client.get(shown).json()
    assert (
        told["next"] and told["can_claim"] is True and told["umpire"] == "" and told["scorecard_id"] is None
    )
    nxt = Match.objects.get(pk=told["next"]["match_id"])

    taken = client.post(claim).json()

    assert taken["scorecard_id"] and taken["can_claim"] is False
    assert umpire_of(nxt) == zuri
    assert Match.objects.get(pk=nxt.pk).held_table_id == one.id
    assert MatchDayLog.objects.filter(
        action="umpire_assigned", match=nxt, summary__contains="took it"
    ).exists()
    # Claiming again changes nothing.
    assert client.post(claim).json()["scorecard_id"] == taken["scorecard_id"]


def test_a_match_somebody_already_umpires_cant_be_claimed(staff, club, hall):  # noqa: F811
    game, zuri, deck, _ = finished(staff, club, hall)
    shown, claim = paths(deck)
    deck.confirm()
    nxt = Match.objects.get(pk=logged_in(zuri).get(shown).json()["next"]["match_id"])
    other = person("Imani Umpire")
    add_member(club, other)
    add_umpire(staff, game, other)
    assign(staff, {**game, "match": nxt}, other)
    told = logged_in(zuri).get(shown).json()
    assert told["can_claim"] is False and told["umpire"] == "Imani Umpire"
    response = logged_in(zuri).post(claim)
    assert response.status_code == 409 and response.json()["code"] == "has_umpire"
    assert umpire_of(nxt) == other


def test_nobody_else_claims_through_somebody_elses_sheet(staff, club, hall):  # noqa: F811
    game, zuri, deck, _ = finished(staff, club, hall)
    _, claim = paths(deck)
    deck.confirm()
    assert logged_in(make_user("nosy@example.com")).post(claim).status_code == 404
    assert staff.post(claim).status_code == 404
