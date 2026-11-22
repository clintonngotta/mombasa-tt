"""The live score channel (REQ-043, EVAL-043, TASK-084): a match being scored reaches everybody who may
see the tournament, as the server replayed it, with nothing the umpire scores with; a score message
names its match; the live list costs the same few queries however many matches are in play."""

from unittest import mock

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from competitions.models import Match
from realtime import broadcast

from .helpers import logged_in, make_user
from .test_draws import draw_url, fill
from .test_roles import add_member
from .test_tournaments import add_event, do, make_tournament
from .test_umpire_scoring import START, Deck, assign, final, match_url, point, scorers  # noqa: F401
from .test_venues import make_venue

pytestmark = pytest.mark.django_db

# What only the umpire's deck works with: none of it may reach a live view (REQ-010).
DECK_ONLY = {"scorecard_id", "assignment_id", "events", "note", "device_id", "can_score", "can_disqualify"}


def live_url(tournament) -> str:
    return f"/api/v1/tournaments/{tournament['id']}/live/"


def umpire_deck(staff, club, game, email="zuri@example.com") -> Deck:
    user = make_user(email, display_name=email.split("@")[0].title())
    add_member(club, user, scorers(club))
    assign(staff, game, user)
    client = logged_in(user)
    return Deck(client, client.get(match_url(game)).json()["scoring"]["scorecard_id"])


def keys(value) -> set:
    """Every key anywhere in a JSON value."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys(item)}
    return set()


def test_a_match_being_scored_is_live_for_everybody_with_nothing_to_score_with(staff, club, final):  # noqa: F811
    deck = umpire_deck(staff, club, final)
    anybody = APIClient()
    assert anybody.get(live_url(final["cup"])).json() == []  # assigned, not started: nothing to show

    deck.send(START, *[point("a")] * 11, point("b"), point("a"), {"type": "timeout", "side": "b"})
    deck.send({"type": "card", "player": "b1", "reason": "delay", "note": "Slow back to the table"})
    shown = anybody.get(live_url(final["cup"])).json()
    assert len(shown) == 1
    (match,) = shown
    assert match["match_id"] == str(final["match"].id) and match["event_name"] == "Singles"
    assert match["round"] == "Final" and match["rubber"] is None and match["rubbers_won"] is None
    score = match["score"]
    assert (score["status"], score["games"], score["games_won"], score["points"]) == (
        "in_progress",
        [[11, 0]],
        [1, 0],
        [1, 1],
    )
    assert score["timeouts"] == [False, True] and score["timeout_running"] == [False, True]
    assert score["server"] in ("a", "b") and score["server_name"]
    assert match["cards"] == [
        {
            "side": "b",
            "player_name": match["b"],
            "card": "yellow",
            "penalty_points": 0,
            "adviser": False,
            "reason": "delay",
            "game_number": 2,
        }
    ]
    assert not keys(shown) & DECK_ONLY
    # The match page carries the same score, and still offers no deck to anybody but its umpire.
    page = anybody.get(match_url(final)).json()["scoring"]
    assert page["live"] == score and page["scorecard_id"] is None and page["can_score"] is False

    # Confirmed, it is a result and no longer live.
    deck.send(*[point("a")] * 10)
    assert anybody.get(live_url(final["cup"])).json()[0]["score"]["status"] == "completed"
    deck.confirm()
    assert anybody.get(live_url(final["cup"])).json() == []


def test_a_draft_tournaments_live_list_is_for_its_organizers_only(staff, club):
    draft = add_event(staff, make_tournament(staff, club, make_venue(staff, club)))
    assert APIClient().get(live_url(draft)).status_code == 404
    assert logged_in(make_user("fan@example.com")).get(live_url(draft)).status_code == 404
    assert staff.get(live_url(draft)).json() == []


def test_a_score_message_names_its_match(staff, club, final):  # noqa: F811
    deck = umpire_deck(staff, club, final)
    with mock.patch.object(broadcast, "tournament_changed") as told:
        deck.send(START, point("a"))
    (tournament, topic), named = told.call_args
    assert (str(tournament), topic) == (final["cup"]["id"], "scores")
    assert named == {"event_id": final["match"].draw.event_id, "match_id": final["match"].id}
    told.assert_called_once()


def test_the_live_list_costs_the_same_queries_for_one_match_or_several(staff, club):
    tournament = add_event(
        staff,
        make_tournament(staff, club, make_venue(staff, club)),
        name="Singles",
        format="knockout",
        best_of=3,
    )
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    fill(staff, tournament, event, 8)
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    first_round = list(Match.objects.filter(draw__event_id=event["id"], round=1).order_by("position"))
    viewer = APIClient()

    def queries() -> int:
        cache.clear()  # the list as worked out, not the second-old copy every viewer shares
        with CaptureQueriesContext(connection) as ran:
            assert viewer.get(live_url(tournament)).status_code == 200
        return len(ran)

    for number, game in enumerate(first_round, start=1):
        deck = umpire_deck(
            staff, club, {"cup": tournament, "event": event, "match": game}, f"u{number}@example.com"
        )
        deck.send(START, point("a"), {"type": "card", "player": "a1", "reason": "delay"})
        if number == 1:
            one = queries()
    assert len(viewer.get(live_url(tournament)).json()) == len(first_round) == 4
    assert queries() == one


def test_signed_out_live_reads_have_their_own_allowance_per_address(staff, club, final, settings):  # noqa: F811
    from rest_framework.settings import api_settings
    from rest_framework.throttling import SimpleRateThrottle

    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**rates, "public_reads": "1/min", "live_reads": "3/min"},
    }
    SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
    try:
        cache.clear()
        visitor = APIClient()
        answers = [visitor.get(live_url(final["cup"])).status_code for _ in range(4)]
        assert answers == [200, 200, 200, 429]  # past the pages' 1/min, within its own 3/min, then held
        spoofed = visitor.get(live_url(final["cup"]), HTTP_X_FORWARDED_FOR="203.0.113.9, 127.0.0.1")
        assert spoofed.status_code == 429
        assert staff.get(live_url(final["cup"])).status_code == 200
    finally:
        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates}
        SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
        cache.clear()


def test_a_match_decided_without_its_sheet_confirmed_leaves_the_list(staff, club, final):  # noqa: F811
    from competitions import drawing

    deck = umpire_deck(staff, club, final)
    deck.send(START, point("a"))
    assert len(APIClient().get(live_url(final["cup"])).json()) == 1
    match = Match.objects.get(pk=final["match"].pk)
    drawing.record_result(match, match.entry_b, outcome="walkover", games=[])
    cache.clear()
    assert APIClient().get(live_url(final["cup"])).json() == []
