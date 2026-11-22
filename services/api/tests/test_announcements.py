"""Results announcements (REQ-043, EVAL-043, TASK-085): drafts drawn only from official results, in the
match card's order, with W/O, ret., DQ and pending matches marked and nothing private; staff edit and
publish them to the tournament's news feed, where they are frozen; a correction marks a post outdated and
an amendment is published beside it."""

from datetime import UTC, datetime, time

import pytest
from rest_framework.test import APIClient

from competitions import drawing
from competitions.models import Announcement, Match, ScheduleSession
from competitions.official import title
from notifications.models import Notification

from .helpers import logged_in, make_user
from .test_draws import draw_url, fill
from .test_ties import cup, tie  # noqa: F401
from .test_tournaments import add_event, do, make_tournament
from .test_venues import make_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def knockout(staff, club):
    """Four players, two semi-finals and a final, best of 5, the tournament under way."""
    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(staff, tournament, name="Singles", format="knockout", best_of=5)
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    fill(staff, tournament, event, 4)
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    semis = list(Match.objects.filter(draw__event_id=event["id"], round=1).order_by("position"))
    return {"cup": tournament, "event": event, "semis": semis}


def news_url(game, *rest) -> str:
    return f"/api/v1/tournaments/{game['cup']['id']}/announcements/" + "".join(f"{part}/" for part in rest)


def names(match: Match) -> tuple[str, str]:
    match.refresh_from_db()
    return title(match.entry_a), title(match.entry_b)


def generate(staff, game, **asked) -> dict:
    response = staff.post(news_url(game), asked, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_the_draft_lists_every_match_from_its_official_result_and_marks_retirements_and_pending(
    staff, knockout
):
    first, second = knockout["semis"]
    drawing.record_result(first, first.entry_a, games=[(11, 7), (9, 11), (11, 5), (11, 8)])
    drawing.record_result(second, second.entry_b, outcome="retired", games=[(11, 5), (3, 11), (4, 2)])
    final = Match.objects.get(draw__event_id=knockout["event"]["id"], round=2)
    a1, b1 = names(first)
    a2, b2 = names(second)
    fa, fb = names(final)
    made = generate(staff, knockout, scope="tournament")
    assert made["status"] == "draft" and made["title"] == "Coast Open: results"
    assert made["body"] == "\n".join(
        [
            "Coast Open: results",
            "",
            "Singles",
            "Semi-final",
            f"{a1} 3-1 {b1} (11-7, 9-11, 11-5, 11-8)",
            f"{a2} 1-1 {b2} (11-5, 3-11, 4-2) ret., {b2} wins",
            "Final",
            f"{fa} v {fb}: pending",
        ]
    )
    assert "@" not in made["body"]  # names and scores only: no emails or anything else private


def test_a_round_marks_a_walkover_and_a_disqualification(staff, knockout):
    first, second = knockout["semis"]
    drawing.record_result(first, first.entry_b, outcome="walkover", games=[])
    drawing.record_result(second, second.entry_a, outcome="disqualified", games=[(11, 3), (5, 2)])
    a1, b1 = names(first)
    a2, b2 = names(second)
    made = generate(
        staff, knockout, scope="round", event_id=knockout["event"]["id"], stage="knockout", round=1
    )
    assert made["title"] == "Coast Open: Singles, semi-final results"
    assert made["body"].splitlines()[2:] == [
        "Singles",
        "Semi-final",
        f"{a1} v {b1}: W/O, {b1} goes through",
        f"{a2} 1-0 {b2} (11-3, 5-2) DQ, {a2} wins",
    ]


def test_a_completed_event_ends_with_its_podium(staff, knockout):
    first, second = knockout["semis"]
    drawing.record_result(first, first.entry_a, games=[(11, 1)] * 3)
    drawing.record_result(second, second.entry_a, games=[(11, 1)] * 3)
    final = Match.objects.get(draw__event_id=knockout["event"]["id"], round=2)
    drawing.record_result(final, final.entry_b, games=[(1, 11)] * 3)
    do(staff, knockout["cup"], "complete", event=knockout["event"])
    final.refresh_from_db()
    body = generate(staff, knockout, scope="event", event_id=knockout["event"]["id"])["body"]
    assert body.splitlines()[-3:] == [
        f"Winner: {title(final.entry_b)}",
        f"Runner-up: {title(final.entry_a)}",
        f"Third place: {title(first.entry_b)} and {title(second.entry_b)}",  # the semi-finals' losers, joint
    ]


def test_a_session_covers_the_matches_scheduled_in_it(staff, knockout):
    first, second = knockout["semis"]
    session = ScheduleSession.objects.create(
        tournament_id=knockout["cup"]["id"],
        name="Saturday morning",
        day="2026-12-05",
        starts=time(9),
        ends=time(12),
    )
    # Venue time is Africa/Nairobi (UTC+3): 10:00 there is 07:00 UTC; 13:00 there is outside the session.
    Match.objects.filter(pk=first.pk).update(scheduled_at=datetime(2026, 12, 5, 7, tzinfo=UTC))
    Match.objects.filter(pk=second.pk).update(scheduled_at=datetime(2026, 12, 5, 10, tzinfo=UTC))
    made = generate(staff, knockout, scope="session", session_id=str(session.id))
    a1, b1 = names(first)
    assert made["title"] == "Coast Open: Saturday morning (09:00-12:00) results"
    assert made["body"].splitlines()[2:] == ["Singles", "Semi-final", f"{a1} v {b1}: pending"]


def test_a_scope_outside_the_tournament_is_refused(staff, club, knockout):
    other = add_event(staff, make_tournament(staff, club, name="Other"))
    for asked in (
        {"scope": "event", "event_id": other["events"][0]["id"]},
        {"scope": "round", "event_id": knockout["event"]["id"], "stage": "group", "round": 1},
        {"scope": "day"},
        {"scope": "session"},
    ):
        response = staff.post(news_url(knockout), asked, format="json")
        assert (response.status_code, response.json()["code"]) == (400, "invalid_scope"), asked


def test_publishing_freezes_it_notifies_and_a_correction_brings_an_amendment(staff, knockout):
    first, _ = knockout["semis"]
    drawing.record_result(first, first.entry_a, games=[(11, 7), (11, 9), (11, 5)])
    made = generate(
        staff, knockout, scope="round", event_id=knockout["event"]["id"], stage="knockout", round=1
    )
    anybody = APIClient()
    assert anybody.get(news_url(knockout)).json()["results"] == []  # a draft is the organizers'
    assert anybody.get(news_url(knockout, made["id"])).status_code == 404
    edited = staff.patch(news_url(knockout, made["id"]), {"title": "Semi-final results"}, format="json")
    assert edited.json()["title"] == "Semi-final results"

    published = staff.post(news_url(knockout, made["id"], "publish"), {"notify": True}, format="json")
    assert published.json()["status"] == "published" and published.json()["published_at"]
    players = {place.user_id for entry in (first.entry_a, first.entry_b) for place in entry.players.all()}
    told = set(
        Notification.objects.filter(subject=f"announcement:{made['id']}").values_list(
            "recipient_id", flat=True
        )
    )
    assert players <= told
    # Frozen.
    again = staff.patch(news_url(knockout, made["id"]), {"body": "Changed"}, format="json")
    assert (again.status_code, again.json()["code"]) == (409, "announcement_published")
    assert staff.delete(news_url(knockout, made["id"])).status_code == 409
    feed = anybody.get(news_url(knockout)).json()["results"]
    assert [post["id"] for post in feed] == [made["id"]]
    card = anybody.get(news_url(knockout, made["id"], "card"))
    assert card.status_code == 200 and card["Content-Type"] == "image/svg+xml"

    # The result is corrected: the post is outdated, an amendment is drawn from the result as it is now.
    corrected = staff.post(
        f"/api/v1/tournaments/{knockout['cup']['id']}/events/{knockout['event']['id']}/matches/{first.id}/result/correct/",
        {
            "winner_entry_id": str(first.entry_a_id),
            "outcome": "played",
            "games": [[11, 7], [11, 9], [12, 10]],
            "rubber_id": None,
            "reason": "Last game misread",
        },
        format="json",
    )
    assert corrected.status_code == 200, corrected.json()
    original = anybody.get(news_url(knockout, made["id"])).json()
    assert original["outdated_at"] and original["body"] == made["body"]  # outdated, never rewritten
    amended = staff.post(news_url(knockout, made["id"], "amend"))
    assert amended.status_code == 201
    amendment = amended.json()
    assert amendment["amends_id"] == made["id"] and "(11-7, 11-9, 12-10)" in amendment["body"]
    staff.post(news_url(knockout, amendment["id"], "publish"), {}, format="json")
    feed = anybody.get(news_url(knockout)).json()["results"]
    assert [post["id"] for post in feed] == [amendment["id"], made["id"]]  # the original stays visible
    assert feed[1]["amended_by_id"] == amendment["id"]
    assert Announcement.objects.count() == 2


def test_only_the_hosts_staff_write_and_a_drafts_news_is_theirs(staff, club, knockout):
    fan = logged_in(make_user("fan@example.com"))
    refused = fan.post(news_url(knockout), {"scope": "tournament"}, format="json")
    assert refused.status_code == 403
    draft = add_event(staff, make_tournament(staff, club, name="Not yet"))
    hidden = {"cup": draft}
    assert APIClient().get(news_url(hidden)).status_code == 404
    assert fan.post(news_url(hidden), {"scope": "tournament"}, format="json").status_code == 404
    assert staff.get(news_url(hidden)).status_code == 200


def test_a_team_tie_counts_its_rubbers_and_lists_them(staff, tie):  # noqa: F811
    from competitions import ties

    from .test_ties import WIN, begin

    rubbers = begin(staff, tie)
    match = tie["match"]
    winner = match.entry_a
    for rubber in rubbers[:3]:
        ties.record_rubber(rubber, winner, games=WIN)
    game = {"cup": tie["cup"]}
    body = generate(staff, game, scope="tournament")["body"]
    a, b = names(match)
    assert f"{a} 3-0 {b}" in body.splitlines()
    assert sum(1 for line in body.splitlines() if line.startswith("  Rubber ")) == 3


def test_sides_still_to_be_decided_are_pending_too(staff, knockout):
    body = generate(staff, knockout, scope="event", event_id=knockout["event"]["id"])["body"]
    assert body.splitlines()[-1] == "To be decided v To be decided: pending"  # the final


def test_a_first_result_outdates_nothing_and_a_post_is_amended_once_at_a_time(staff, knockout):
    first, second = knockout["semis"]
    drawing.record_result(first, first.entry_a, games=[(11, 1)] * 3)
    made = generate(staff, knockout, scope="tournament")
    staff.post(news_url(knockout, made["id"], "publish"), {}, format="json")
    drawing.record_result(second, second.entry_a, games=[(11, 1)] * 3)  # a first result for the other semi
    assert staff.get(news_url(knockout, made["id"])).json()["outdated_at"] is None
    assert staff.post(news_url(knockout, made["id"], "amend")).status_code == 201
    again = staff.post(news_url(knockout, made["id"], "amend"))
    assert (again.status_code, again.json()["code"]) == (409, "amendment_pending")


def test_a_drafts_card_is_the_staffs_and_its_text_is_escaped(staff, knockout):
    made = generate(staff, knockout, scope="tournament")
    staff.patch(
        news_url(knockout, made["id"]),
        {"title": "<script>x</script>", "body": "Head\n<b>&</b>"},
        format="json",
    )
    assert APIClient().get(news_url(knockout, made["id"], "card")).status_code == 404
    card = staff.get(news_url(knockout, made["id"], "card")).content.decode()
    assert "<script>" not in card and "&lt;script&gt;" in card and "&lt;b&gt;&amp;&lt;/b&gt;" in card


def test_only_players_holding_a_place_are_told(staff, knockout):
    from competitions.models import Entry

    first, _ = knockout["semis"]
    gone = first.entry_b
    Entry.objects.filter(pk=gone.pk).update(status=Entry.Status.WITHDRAWN)
    made = generate(staff, knockout, scope="tournament")
    staff.post(news_url(knockout, made["id"], "publish"), {"notify": True}, format="json")
    told = set(Notification.objects.values_list("recipient_id", flat=True))
    assert gone.players.get().user_id not in told and first.entry_a.players.get().user_id in told


def test_drafting_costs_the_same_queries_for_a_small_draw_or_a_big_one(staff, club):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def bracket(size: int, name: str) -> dict:
        made = add_event(
            staff,
            make_tournament(staff, club, make_venue(staff, club, name=f"{name} hall"), name=name),
            name=f"{name} singles",
            format="knockout",
        )
        made = do(staff, made, "publish")
        event = made["events"][0]
        fill(staff, made, event, size)
        staff.post(draw_url(made, event, "preview"), {"rng_seed": 1}, format="json")
        staff.post(draw_url(made, event, "publish"), {}, format="json")
        do(staff, made, "start")
        do(staff, made, "start", event=event)
        for match in Match.objects.filter(draw__event_id=event["id"], round=1):
            drawing.record_result(match, match.entry_a, games=[(11, 1)] * 3)
        return {"cup": made}

    def queries(game) -> int:
        with CaptureQueriesContext(connection) as ran:
            generate(staff, game, scope="tournament")
        return len(ran)

    assert queries(bracket(4, "Small")) == queries(bracket(16, "Big"))
