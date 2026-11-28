"""Completing an event needs every result in, and a platform super admin can reopen one that was
completed too early (REQ-007)."""

import pytest

from competitions.models import Event, LifecycleEntry, Match

from .helpers import logged_in, make_user
from .test_official_results import correct, enter, fresh, hall, knockout  # noqa: F401 (hall is a fixture)
from .test_reservations import started
from .test_tournaments import do, url

pytestmark = pytest.mark.django_db

REASON = "Completed before the final was played"


@pytest.fixture
def root():
    return logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))


def event_of(tournament: dict, event: dict) -> dict:
    return next(e for e in tournament["events"] if e["id"] == event["id"])


def reopen(client, game, reason=REASON):
    return client.post(url(game["cup"], "reopen", game["event"]), {"reason": reason}, format="json")


def finished(staff, club, hall) -> dict:  # noqa: F811
    """A one-match event with its result in, completed."""
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    match = fresh(game["match"])
    enter(staff, game, match, match.entry_a, outcome="walkover")
    do(staff, game["cup"], "complete", event=game["event"])
    return game


def test_an_event_cant_be_completed_while_a_match_has_no_result(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    shown = staff.get(url(game["cup"])).json()
    assert event_of(shown, game["event"])["matches_left"] == 3

    refused = staff.post(url(game["cup"], "complete", game["event"]), {}, format="json")
    assert refused.status_code == 409
    assert refused.json()["code"] == "matches_left"
    assert "3 matches have no result yet" in refused.json()["message"]
    assert Event.objects.get(pk=game["event"]["id"]).status == Event.Status.IN_PROGRESS

    for semi in game["semis"]:
        semi = fresh(semi)
        enter(staff, game, semi, semi.entry_a, outcome="walkover")
    shown = staff.get(url(game["cup"])).json()
    assert event_of(shown, game["event"])["matches_left"] == 1
    assert staff.post(url(game["cup"], "complete", game["event"]), {}, format="json").status_code == 409

    final = fresh(game["final"])
    enter(staff, game, final, final.entry_a, outcome="walkover")
    done = do(staff, game["cup"], "complete", event=game["event"])
    assert event_of(done, game["event"])["matches_left"] == 0
    assert event_of(done, game["event"])["status"] == "completed"


def test_a_super_admin_reopens_a_completed_event_with_a_reason(staff, root, club, hall):  # noqa: F811
    game = finished(staff, club, hall)
    response = reopen(root, game)
    assert response.status_code == 200, response.json()
    event = event_of(response.json(), game["event"])
    assert (event["status"], event["completed_at"]) == ("in_progress", None)

    logged = LifecycleEntry.objects.filter(action=LifecycleEntry.Action.EVENT_REOPENED).get()
    assert (logged.reason, logged.actor.email, logged.event_id) == (
        REASON,
        "root@example.com",
        game["match"].draw.event_id,
    )
    history = staff.get(url(game["cup"], "history")).json()
    assert any(row["action"] == "event_reopened" and row["reason"] == REASON for row in history)

    # Back in progress, so results can be corrected and the event completed again.
    match = fresh(game["match"])
    correct(staff, game, match, match.entry_b, outcome="walkover")
    assert fresh(match).winner_id == match.entry_b_id
    do(staff, game["cup"], "complete", event=game["event"])


def test_only_a_platform_super_admin_reopens_an_event(staff, club, hall):  # noqa: F811
    game = finished(staff, club, hall)
    stranger = logged_in(make_user("stranger@example.com"))
    for client in (staff, stranger):
        assert reopen(client, game).status_code == 404
    assert Event.objects.get(pk=game["event"]["id"]).status == Event.Status.COMPLETED
    assert not LifecycleEntry.objects.filter(action=LifecycleEntry.Action.EVENT_REOPENED).exists()


def test_reopening_needs_a_reason_and_a_completed_event_of_a_running_tournament(
    staff,
    root,
    club,
    hall,  # noqa: F811
):
    game = finished(staff, club, hall)
    assert reopen(root, game, reason="").status_code == 400
    assert reopen(root, game, reason="x" * 301).status_code == 400

    assert reopen(root, game).status_code == 200
    again = reopen(root, game)  # in progress now
    assert (again.status_code, again.json()["code"]) == (409, "invalid_transition")

    match = Match.objects.get(pk=game["match"].pk)
    assert match.status == Match.Status.COMPLETED
    do(staff, game["cup"], "complete", event=game["event"])
    do(staff, game["cup"], "complete")
    closed = reopen(root, game)
    assert (closed.status_code, closed.json()["code"]) == (409, "tournament_not_running")


def test_reopening_an_unknown_event_is_not_found(root, staff, club, hall):  # noqa: F811
    game = finished(staff, club, hall)
    missing = {**game, "event": {"id": "00000000-0000-0000-0000-000000000000"}}
    assert reopen(root, missing).status_code == 404
