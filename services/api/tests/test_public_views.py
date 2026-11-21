"""Public tournament pages and the organizer dashboard (REQ-020, EVAL-020, TASK-035)."""

import pytest
from django.core.cache import cache

from competitions.models import Ceremony, Match

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_official_results import GAMES, enter, knockout
from .test_tournaments import make_tournament, url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def test_a_signed_out_visitor_follows_a_published_tournament(staff, club, hall):
    game = knockout(staff, club, hall)
    cup, event, semi = game["cup"], game["event"], game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    visitor = BrowserClient()

    listed = visitor.get("/api/v1/tournaments/?when=upcoming")
    assert listed.status_code == 200
    assert cup["id"] in [t["id"] for t in listed.json()["results"]]
    assert visitor.get(url(cup)).json()["name"] == cup["name"]
    entries = visitor.get(url(cup, event=event) + "entries/").json()["results"]
    assert len(entries) == 4 and not any(entry["mine"] for entry in entries)
    assert all(entry["my_check_in_at"] is None for entry in entries)
    assert visitor.get(url(cup, event=event) + "draw/").json()["preview"] is None
    assert visitor.get(url(cup, event=event) + "standings/").status_code == 200
    shown = visitor.get(url(cup, event=event) + f"matches/{semi.id}/").json()
    assert shown["result"]["recorded_by"] == "" and shown["result"]["reason"] == ""
    assert shown["result_history"] == [] and not shown["can_record_result"]
    assert shown["scoring"]["scorecard_id"] is None and not shown["scoring"]["can_score"]
    assert visitor.get("/api/v1/rankings/").status_code == 200
    winner = semi.entry_a.players.first().user
    assert visitor.get(f"/api/v1/ratings/players/{winner.id}/").status_code in (200, 404)

    # Reading is all a visitor does: changes and the organizers' pages still need a session.
    assert visitor.get(url(cup, "history")).status_code == 401
    assert visitor.get(url(cup, "dashboard")).status_code == 401
    assert visitor.post(url(cup, event=event) + "entries/", {}, format="json").status_code in (401, 403)
    assert visitor.get(f"/api/v1/rankings/?organization={club.id}").status_code == 401


def test_drafts_stay_hidden_from_visitors(staff, club, hall):
    draft = make_tournament(staff, club, hall)
    visitor = BrowserClient()
    assert visitor.get(url(draft)).status_code == 404
    assert draft["id"] not in [t["id"] for t in visitor.get("/api/v1/tournaments/").json()["results"]]


def test_a_draft_ceremony_is_the_organizers_until_published(staff, club, hall):
    game = knockout(staff, club, hall)
    cup = game["cup"]
    staff.put(url(cup, "ceremony"), {"location": "Main hall"}, format="json")
    visitor = BrowserClient()
    assert visitor.get(url(cup, "ceremony")).status_code == 404
    Ceremony.objects.filter(tournament_id=cup["id"]).update(status=Ceremony.Status.PUBLISHED)
    assert visitor.get(url(cup, "ceremony")).json()["location"] == "Main hall"


def test_signed_out_reads_are_throttled_per_address(staff, club, hall, settings):
    cup = make_tournament(staff, club, hall)
    staff.post(url(cup, "publish"), {}, format="json")
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**rates, "public_reads": "3/min"},
    }
    from rest_framework.settings import api_settings
    from rest_framework.throttling import SimpleRateThrottle

    SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
    try:
        cache.clear()
        visitor = BrowserClient()
        answers = [visitor.get("/api/v1/tournaments/").status_code for _ in range(4)]
        assert answers == [200, 200, 200, 429]
        # A spoofed X-Forwarded-For doesn't buy a fresh allowance: the proxy's own hop is used.
        spoofed = visitor.get("/api/v1/tournaments/", HTTP_X_FORWARDED_FOR="203.0.113.9, 127.0.0.1")
        assert spoofed.status_code == 429
        # Signed-in players aren't held to the visitors' allowance.
        assert logged_in(make_user("fan@example.com")).get("/api/v1/tournaments/").status_code == 200
    finally:
        settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": rates}
        SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES


def test_the_dashboard_counts_where_each_event_stands(staff, club, hall, django_assert_max_num_queries):
    game = knockout(staff, club, hall)
    cup, semi = game["cup"], game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    reply = staff.get(url(cup, "dashboard"))
    assert reply.status_code == 200
    board = reply.json()
    event = board["events"][0]
    assert event["entries"] == {"pending": 0, "accepted": 4, "waitlisted": 0, "checked_in": 4}
    assert event["draw"] == "published"
    assert event["matches"]["total"] == 3 and event["matches"]["decided"] == 1
    # The other semi is ready; the final waits for its second player.
    assert event["matches"]["ready"] == 1 and event["matches"]["on_table"] == 0
    assert board["entries"] == event["entries"] and board["matches"] == event["matches"]
    assert board["ceremony"] == "none" and board["corrections"] == 0
    assert Match.objects.filter(draw__event_id=event["id"]).count() == 3

    # The query count doesn't grow with the number of events.
    with django_assert_max_num_queries(20):
        staff.get(url(cup, "dashboard"))

    # Staff only: a signed-in player of another club is refused.
    assert logged_in(make_user("fan@example.com")).get(url(cup, "dashboard")).status_code == 403
