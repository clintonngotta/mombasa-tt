"""The draw shows who is on a table right now and which (user request, 2026-11-28): every entry a draw
shows carries `playing` while one of its players is held on a table in the tournament."""

import pytest

from scoring.models import Scorecard

from .helpers import logged_in
from .test_official_results import GAMES, enter, fresh, hall, knockout  # noqa: F401
from .test_reservations import person, send, tables
from .test_roles import add_member
from .test_tournaments import url
from .test_umpire_scoring import START, Deck, assign, point

pytestmark = pytest.mark.django_db


def entries_shown(client, game) -> dict:
    """Entry id -> `playing`, from every place in the published draw."""
    draw = client.get(url(game["cup"], event=game["event"]) + "draw/").json()
    published = draw["published"]
    return {place["entry"]["id"]: place["entry"]["playing"] for place in published["places"]}


def test_a_player_on_a_table_is_shown_there_until_the_result(staff, club, hall, client):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    one, _ = tables(hall)
    assert all(playing is None for playing in entries_shown(staff, game).values())

    send(staff, {**game, "match": first}, one)
    shown = entries_shown(client, game)  # everybody who sees the draw, signed in or not
    for side in (first.entry_a_id, first.entry_b_id):
        assert shown[str(side)] == {
            "table": "Table 1",
            "match_id": str(first.id),
            "event_id": game["event"]["id"],
            "event_name": game["event"]["name"],
            "live": False,
        }
    assert shown[str(second.entry_a_id)] is None and shown[str(second.entry_b_id)] is None

    # Once the first point is scored, it is play, not a call.
    umpire = person("Zuri Ump")
    add_member(club, umpire, "referee")
    assign(staff, {**game, "match": first}, umpire)
    Deck(logged_in(umpire), Scorecard.objects.get(match=first).id).send(START, point("a"))
    assert entries_shown(staff, game)[str(first.entry_a_id)]["live"] is True

    # The result frees the table and the players.
    enter(staff, game, fresh(first), first.entry_a, games=GAMES)
    assert entries_shown(staff, game)[str(first.entry_a_id)] is None
