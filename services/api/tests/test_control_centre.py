"""The match-day control centre (REQ-043, EVAL-043, TASK-082): table states, calls with a grace period,
moves, blocked tables, the check-in desk, the match-day log, and walkovers for the referee alone."""

import uuid
from datetime import datetime, timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from competitions.models import Event, Match, MatchDayLog
from notifications.models import Notification
from reservations.models import Hold, MatchCall, Reservation, TableBlock
from scoring import service as scoring

from .helpers import logged_in, make_user
from .test_official_results import correct, enter, fresh, knockout
from .test_reservations import person, send, started, tables
from .test_roles import add_member
from .test_tournaments import url

pytestmark = pytest.mark.django_db


@pytest.fixture
def hall(staff, club):
    from .test_venues import add_table, make_venue

    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2", "Table 3"):
        add_table(staff, club, venue, label)
    return venue


def board(client, cup, expect=200) -> dict:
    response = client.get(url(cup) + "dispatch/")
    assert response.status_code == expect, response.json()
    return response.json()


def table_on(shown: dict, label: str) -> dict:
    return next(table for table in shown["tables"] if table["label"] == label)


def act(client, game, action, expect=200, **body) -> dict:
    path = url(game["cup"], event=game["event"]) + f"matches/{game['match'].id}/{action}/"
    response = client.post(path, body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def block(client, game, table, expect=200, **body) -> dict:
    body = {"reason": "out_of_service", **body}
    response = client.post(url(game["cup"]) + f"tables/{table.id}/block/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def unblock(client, game, table, expect=200) -> dict:
    response = client.post(url(game["cup"]) + f"tables/{table.id}/unblock/", {}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def log(client, cup, **params) -> list[dict]:
    response = client.get(url(cup) + "match-day-log/", params)
    assert response.status_code == 200, response.json()
    return response.json()


def staff_member(club, email, *roles):
    user = make_user(email)
    add_member(club, user, *roles)
    return logged_in(user)


def score_a_point(game, umpire):
    with transaction.atomic():
        card = scoring.assign(game["match"], None, umpire, umpire)
    events = [
        {"type": "start", "server": "a1", "a_end": "left"},
        {"type": "point", "side": "a"},
    ]
    sent = [{"id": str(uuid.uuid4()), "sequence": n, "event": event} for n, event in enumerate(events, 1)]
    with transaction.atomic():
        card.refresh_from_db()
        assert scoring.submit(card, umpire, card.assignment_id, sent)["accepted"] == 2


def test_a_table_goes_from_free_to_called_to_warming_up_to_in_play(staff, club, hall):
    one, *_ = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    assert table_on(board(staff, game["cup"]), "Table 1")["state"] == "free"
    send(staff, game, one)
    shown = table_on(board(staff, game["cup"]), "Table 1")
    assert shown["state"] == "called"
    assert shown["call"]["calls"] == 1 and shown["call"]["no_show"] == []
    act(staff, game, "report", side="a")
    assert table_on(board(staff, game["cup"]), "Table 1")["state"] == "called"
    shown = table_on(act(staff, game, "report", side="b"), "Table 1")
    assert shown["state"] == "warming_up"
    assert shown["call"]["a_reported_at"] and shown["call"]["b_reported_at"]
    # Once a point is scored the table is in play, with the umpire and the live score on the board.
    umpire = person("Umpire Una")
    add_member(club, umpire, "assistant_captain")
    score_a_point(game, umpire)
    shown = table_on(board(staff, game["cup"]), "Table 1")
    assert shown["state"] == "in_play"
    assert shown["umpire"] == "Umpire Una"
    assert shown["score"]["points"] == [1, 0] and shown["score"]["games_won"] == [0, 0]
    # Undoing a report is refused once the match is being played.
    assert act(staff, game, "report", expect=409, side="a", undo=True)["code"] == "already_playing"


def test_a_side_not_at_the_table_after_the_grace_period_is_flagged(staff, club, hall):
    one, *_ = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    Event.objects.filter(pk=game["event"]["id"]).update(call_grace_minutes=5)
    send(staff, game, one)
    act(staff, game, "report", side="a")
    assert table_on(board(staff, game["cup"]), "Table 1")["call"]["no_show"] == []
    Reservation.objects.filter(match=game["match"]).update(called_at=timezone.now() - timedelta(minutes=6))
    shown = table_on(board(staff, game["cup"]), "Table 1")
    assert shown["state"] == "called" and shown["call"]["no_show"] == ["b"]
    # The flag is a fact for the referee; it decides nothing by itself.
    assert fresh(game["match"]).status == Match.Status.SCHEDULED
    act(staff, game, "report", side="b")
    assert table_on(board(staff, game["cup"]), "Table 1")["call"]["no_show"] == []


def test_calling_again_tells_only_the_side_not_yet_at_the_table(staff, club, hall):
    one, *_ = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    send(staff, game, one)
    act(staff, game, "report", side="a")
    shown = table_on(act(staff, game, "call"), "Table 1")
    assert shown["call"]["calls"] == 2
    again = Notification.objects.filter(title="Called again to Table 1")
    side_b = game["match"].entry_b.players.get().user
    assert [note.recipient for note in again] == [side_b]
    assert MatchCall.objects.filter(match=game["match"]).count() == 2


def test_a_match_moves_to_another_table_with_its_call_and_who_reported(staff, club, hall):
    one, two, three = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    send(staff, game, one)
    act(staff, game, "report", side="a")
    first_call = Reservation.objects.get(match=game["match"]).called_at
    assert act(staff, game, "move", expect=409, table_id=str(one.id), reason="Same")["code"] == "same_table"
    act(staff, game, "move", expect=400, table_id=str(two.id))  # a reason is required
    shown = act(staff, game, "move", table_id=str(two.id), reason="The light over Table 1 went out")
    assert table_on(shown, "Table 1")["state"] == "free"
    moved = table_on(shown, "Table 2")
    assert (
        moved["state"] == "called" and moved["call"]["a_reported_at"] and not moved["call"]["b_reported_at"]
    )
    old, new = Reservation.objects.filter(match=game["match"]).order_by("created_at")
    assert (old.status, old.ending, new.status) == ("released", "moved", "active")
    assert new.called_at == first_call
    # The move calls the match to its new table, and the count of calls goes on from before.
    assert moved["call"]["calls"] == 2
    assert datetime.fromisoformat(moved["call"]["called_at"]) == first_call
    assert Hold.objects.filter(reservation=new, active=True, user__isnull=False).count() == 2
    assert fresh(game["match"]).table_id == two.id
    entry = log(staff, game["cup"])[0]
    assert (entry["action"], entry["reason"]) == ("moved", "The light over Table 1 went out")
    assert "from Table 1 to Table 2" in entry["summary"]
    # A table in use or blocked is no place to move to.
    other = started(staff, club, hall, [["Chege"], ["Daudi"]], tournament="Veterans Cup")
    send(staff, other, three)
    assert act(staff, game, "move", expect=409, table_id=str(three.id), reason="x")["code"] == "table_busy"


def test_a_blocked_table_gets_no_match_until_it_is_back_in_use(staff, club, hall):
    one, two, _three = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    shown = block(staff, game, one, note="Net broken")
    blocked = table_on(shown, "Table 1")
    assert blocked["state"] == "blocked"
    assert (blocked["block"]["reason_label"], blocked["block"]["note"]) == ("Out of service", "Net broken")
    assert blocked["suggested_match_id"] is None and blocked["idle_reason"] == ""
    assert table_on(shown, "Table 2")["suggested_match_id"] == str(game["match"].id)
    assert block(staff, game, one, expect=409)["code"] == "already_blocked"
    refused = send(staff, game, one, expect=409)
    assert refused == {**refused, "code": "table_blocked", "message": "Table 1 is blocked: out of service."}
    # A table with a match on it is freed first.
    send(staff, game, two)
    assert block(staff, game, two, expect=409)["code"] == "table_busy"
    assert table_on(unblock(staff, game, one), "Table 1")["state"] == "free"
    assert unblock(staff, game, one, expect=409)["code"] == "not_blocked"
    assert [e["action"] for e in log(staff, game["cup"])[:2]] == ["table_unblocked", "called"]
    assert TableBlock.objects.get(table=one).ended_at is not None


def test_the_log_keeps_who_did_what_and_why(staff, club, hall):
    one, *_ = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]], checked_in=False)
    entry = game["match"].entry_a
    path = url(game["cup"], event=game["event"]) + f"entries/{entry.id}/"
    assert staff.post(path + "check-in/", {}, format="json").status_code == 200
    staff.post(path + "check-in/", {}, format="json")  # checking in twice is one check-in
    assert staff.post(path + "undo-check-in/", {}, format="json").status_code == 200
    send(staff, game, one, overrides=["check_in"], reason="Both here, desk was busy")
    act(staff, game, "recall", reason="Wrong event")
    entries = log(staff, game["cup"])
    assert [e["action"] for e in entries] == ["recalled", "called", "check_in_undone", "checked_in"]
    assert {e["actor"] for e in entries} == {"Club Admin"}
    assert entries[0]["reason"] == "Wrong event" and entries[0]["table"] == "Table 1"
    assert entries[1]["reason"] == "Both here, desk was busy"
    assert entries[3]["summary"] == f"Singles: {entry.players.get().user.display_name}"
    # Filtered to one match, and newest first.
    assert [e["action"] for e in log(staff, game["cup"], match=str(game["match"].id))] == [
        "recalled",
        "called",
    ]
    assert log(staff, game["cup"], match="not-an-id") == []


def test_the_check_in_desk_lists_who_is_still_to_arrive_first(staff, club, hall):
    game = started(staff, club, hall, [["Amina"], ["Brian"], ["Chege"]], checked_in=False)
    first = game["match"].entry_a
    staff.post(url(game["cup"], event=game["event"]) + f"entries/{first.id}/check-in/", {}, format="json")
    response = staff.get(url(game["cup"]) + "check-in-desk/")
    assert response.status_code == 200
    rows = response.json()
    assert [row["checked_in_at"] is None for row in rows] == [True, True, False]
    assert rows[-1]["title"] == first.players.get().user.display_name and rows[-1]["checked_in_by"]


@pytest.mark.parametrize(
    ("role", "outcome", "allowed"),
    [
        ("captain", "walkover", False),
        ("captain", "disqualified", False),
        ("captain", "retired", True),
        ("captain", "played", True),
        ("referee", "walkover", True),
        ("referee", "disqualified", True),
        ("referee", "retired", True),
        ("admin", "walkover", True),
    ],
)
def test_only_the_referee_awards_walkovers_and_disqualifications(staff, club, hall, role, outcome, allowed):
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    client = staff if role == "admin" else staff_member(club, f"{role}@example.com", role)
    games = {"played": [[11, 1], [11, 2], [11, 3]], "retired": [[11, 4], [3, 2]]}.get(outcome, [])
    body = {"outcome": outcome, "games": games, "reason": "No-show after the grace period"}
    shown = enter(client, game, first, first.entry_a, expect=200 if allowed else 403, **body)
    if allowed:
        assert fresh(first).outcome == outcome
        entry = log(staff, game["cup"])[0]
        assert entry["action"] == "result_entered" and entry["reason"] == body["reason"]
    else:
        assert shown["code"] == "referee_only"
        assert fresh(first).status == Match.Status.SCHEDULED


def test_only_the_referee_takes_a_walkover_away(staff, club, hall):
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    enter(staff, game, first, first.entry_a, outcome="walkover")
    captain = staff_member(club, "captain@example.com", "captain")
    played = [[11, 1], [11, 2], [11, 3]]
    assert correct(captain, game, first, first.entry_a, expect=403, games=played)["code"] == "referee_only"
    referee = staff_member(club, "referee@example.com", "referee")
    correct(referee, game, first, first.entry_a, games=played)
    assert fresh(first).outcome == Match.Outcome.PLAYED
    assert MatchDayLog.objects.filter(action="result_corrected").count() == 1


def test_the_control_centre_is_for_the_hosts_competition_staff(staff, club, hall):
    one, *_ = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    send(staff, game, one)
    member = staff_member(club, "member@example.com")
    referee = staff_member(club, "referee@example.com", "referee")
    for client in (member, referee):
        assert act(client, game, "call", expect=403)
        assert act(client, game, "report", expect=403, side="a")
        assert client.get(url(game["cup"]) + "match-day-log/").status_code == 403
        assert client.get(url(game["cup"]) + "check-in-desk/").status_code == 403
        assert block(client, game, one, expect=403)


def test_the_match_page_offers_walkovers_to_the_referee_alone(staff, club, hall):
    game = knockout(staff, club, hall)
    first = game["semis"][0]
    page = f"/api/v1/tournaments/{game['cup']['id']}/events/{game['event']['id']}/matches/{first.id}/"
    captain = staff_member(club, "captain@example.com", "captain")
    referee = staff_member(club, "referee@example.com", "referee")
    shown = captain.get(page).json()
    assert shown["can_record_result"] and not shown["can_award_walkover"]
    assert referee.get(page).json()["can_award_walkover"]
    enter(referee, game, first, first.entry_a, outcome="walkover", reason="No-show after the grace period")
    assert not captain.get(page).json()["can_record_result"]
    assert referee.get(page).json()["can_record_result"]


def test_control_routes_refuse_what_is_not_theirs_to_change(staff, club, hall, admin):
    from facilities.models import Table

    one, two, _three = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    # A table of another venue is not found, whatever its id.
    elsewhere = Table.objects.create(
        venue=one.venue.__class__.objects.create(
            organization=one.venue.organization, name="Other hall", town="Mombasa"
        ),
        label="Far table",
    )
    assert block(staff, game, elsewhere, expect=404)
    # A match that isn't on a table can't be called or reported.
    assert act(staff, game, "call", expect=409)["code"] == "not_on_table"
    assert act(staff, game, "report", expect=409, side="a")["code"] == "not_on_table"
    assert act(staff, game, "move", expect=404, table_id=str(elsewhere.id), reason="x")
    send(staff, game, one)
    umpire = person("Umpire Una")
    add_member(club, umpire, "assistant_captain")
    score_a_point(game, umpire)
    assert act(staff, game, "call", expect=409)["code"] == "already_playing"


def test_switching_automatic_dispatch_is_logged(staff, club, hall):
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    for enabled in (True, True, False):
        assert (
            staff.post(url(game["cup"]) + "dispatch/auto/", {"enabled": enabled}, format="json").status_code
            == 200
        )
    actions = [e["action"] for e in log(staff, game["cup"])]
    assert actions.count("auto_on") == 1 and actions[0] == "auto_off"


def test_a_walkovers_reason_stays_with_the_official_result(staff, club, hall):
    from competitions.models import OfficialResult

    game = knockout(staff, club, hall)
    first = game["semis"][0]
    enter(staff, game, first, first.entry_a, outcome="walkover", reason="Withdrew before the start")
    assert OfficialResult.objects.get(match=first, current=True).reason == "Withdrew before the start"


def test_only_the_referee_strikes_out_a_walkover_when_settling_a_correction(staff, club, hall):
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    played = [[11, 1], [11, 2], [11, 3]]
    enter(staff, game, first, first.entry_a, games=played)
    enter(staff, game, second, second.entry_a, games=played)
    final = fresh(game["final"])
    enter(staff, game, final, final.entry_a, outcome="walkover")
    correct(staff, game, first, first.entry_b, games=[[1, 11], [2, 11], [3, 11]])
    waiting = staff.get(url(game["cup"]) + "corrections/").json()[0]
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    captain = staff_member(club, "captain@example.com", "captain")
    refused = captain.post(path, {"choice": "replace", "note": "Replay"}, format="json")
    assert (refused.status_code, refused.json()["code"]) == (403, "referee_only")
    assert captain.post(path, {"choice": "keep", "note": "Stands"}, format="json").status_code == 200
    assert log(staff, game["cup"])[0]["action"] == "correction_settled"
