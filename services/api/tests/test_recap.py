"""Match recaps and result cards (REQ-018, EVAL-018; TASK-032)."""

import pytest

from .conftest import BrowserClient
from .test_official_results import GAMES, enter, hall, knockout  # noqa: F401
from .test_ratings import work
from .test_tournaments import url

pytestmark = pytest.mark.django_db


def recap_url(game, match, tail="recap/"):
    return url(game["cup"], event=game["event"]) + f"matches/{match.id}/{tail}"


def test_a_recap_shows_the_official_result_and_waits_for_the_rating(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    public = BrowserClient()
    before = public.get(recap_url(game, semi)).json()
    assert (before["official"], before["rating"], before["games"]) == (False, "none", [])
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    pending = public.get(recap_url(game, semi)).json()
    # Official, but the rating worker hasn't run: say so instead of inventing a number.
    assert (pending["official"], pending["winner_side"], pending["rating"], pending["rating_changes"]) == (
        True,
        "a",
        "processing",
        [],
    )
    assert pending["games"] == GAMES
    work()
    done = public.get(recap_url(game, semi)).json()
    assert done["rating"] == "done"
    assert sorted((c["before"], c["after"], c["delta"]) for c in done["rating_changes"]) == [
        (1000, 984, -16),
        (1000, 1016, 16),
    ]
    assert {p["display_name"] for p in done["players"]} == {done["side_a"], done["side_b"]}


def test_a_walkover_is_unrated_and_says_so(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    semi = game["semis"][1]
    enter(staff, game, semi, semi.entry_b, outcome="walkover")
    work()
    shown = BrowserClient().get(recap_url(game, semi)).json()
    assert (shown["outcome"], shown["winner_side"], shown["rating"]) == ("walkover", "b", "unrated")


def test_the_card_carries_public_facts_only_and_a_draft_has_none(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    card = BrowserClient().get(recap_url(game, semi, "card.svg"))
    assert card.status_code == 200 and card["Content-Type"] == "image/svg+xml"
    body = card.content.decode()
    assert body.startswith("<svg") and "Coast Open" in body and "11-5" in body and "wins" in body
    assert "@" not in body  # no email or other contact
    # A draft tournament's matches have no recap for anyone.
    from competitions.models import Tournament

    Tournament.objects.filter(pk=game["cup"]["id"]).update(status="draft")
    assert BrowserClient().get(recap_url(game, semi)).status_code == 404
    assert BrowserClient().get(recap_url(game, semi, "card.svg")).status_code == 404
