"""The ready queue, the dispatch board and automatic dispatch (REQ-014, EVAL-014, TASK-028)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from competitions import drawing
from competitions.models import Entry, Match, Tournament
from reservations.models import Hold, Reservation

from .test_reservations import recall, send, started, tables
from .test_roles import create_club  # noqa: F401
from .test_tournaments import url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def board(client, cup, expect=200) -> dict:
    response = client.get(url(cup) + "dispatch/")
    assert response.status_code == expect, response.json()
    return response.json()


def auto(client, cup, enabled=True) -> dict:
    response = client.post(url(cup) + "dispatch/auto/", {"enabled": enabled}, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def run(client, cup) -> dict:
    response = client.post(url(cup) + "dispatch/run/", {}, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def names(queue) -> list[str]:
    return [f"{row['a']} v {row['b']}" for row in queue]


def league(staff, club, hall, players, **event) -> dict:
    """A round robin of singles: every pair of `players` meets once."""
    return started(staff, club, hall, [[name] for name in players], format="round_robin", **event)


def matches_of(game) -> list[Match]:
    return list(Match.objects.filter(draw__event_id=game["event"]["id"]).order_by("round", "position"))


def test_the_queue_orders_by_planned_start_then_longest_wait_then_id(staff, club, hall):
    game = league(staff, club, hall, ["Amina", "Brian", "Chege", "Daudi", "Eli", "Faith"])
    first, second, third, fourth, *_ = matches_of(game)
    now = timezone.now()
    Match.objects.filter(draw__event_id=game["event"]["id"]).update(ready_since=now)
    # A planned start goes first, the earlier one before the later; without one, the longest wait.
    Match.objects.filter(pk=fourth.pk).update(scheduled_at=now + timedelta(minutes=30))
    Match.objects.filter(pk=third.pk).update(scheduled_at=now + timedelta(minutes=5))
    Match.objects.filter(pk=second.pk).update(ready_since=now - timedelta(minutes=20))
    queue = board(staff, game["cup"])["queue"]
    assert [row["match_id"] for row in queue[:3]] == [str(third.id), str(fourth.id), str(second.id)]
    # Everything else is equal: the id decides, the same way every time.
    rest = [row["match_id"] for row in queue[3:]]
    assert rest == sorted(rest)
    assert board(staff, game["cup"])["queue"] == queue


def test_free_tables_are_offered_to_the_first_matches_that_can_be_played(staff, club, hall):
    game = league(staff, club, hall, ["Amina", "Brian", "Chege", "Daudi"])
    shown = board(staff, game["cup"])
    assert (shown["in_play"], shown["auto_dispatch"], shown["to_come"]) == (True, False, 0)
    ready = [row for row in shown["queue"] if row["state"] == "ready"]
    # Two tables, and the two first matches that share no player.
    assert [row["suggested_table"] for row in ready] == ["Table 1", "Table 2"]
    assert len({name for row in ready for name in (row["a"], row["b"])}) == 4
    assert [table["suggested_match_id"] for table in shown["tables"]] == [row["match_id"] for row in ready]
    waiting = [row for row in shown["queue"] if row["state"] == "waiting"]
    assert len(waiting) == 4
    assert {row["reasons"][0]["code"] for row in waiting} == {"plays_earlier_match"}
    assert all(row["position"] for row in waiting)  # they can be played: they have a rank
    assert {row["label"][:6] for row in shown["queue"]} == {"Round "}  # one group: no group name
    assert " is in a match ahead in the queue (" in waiting[0]["reasons"][0]["message"]


def test_a_held_up_match_and_an_idle_table_say_what_really_stands_in_the_way(staff, club, hall):
    one, _ = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]], checked_in=False)
    shown = board(staff, game["cup"])
    (row,) = shown["queue"]
    assert (row["state"], row["position"]) == ("blocked", None)
    assert [reason["code"] for reason in row["reasons"]] == ["not_checked_in"]
    absent = f"{row['a']} and {row['b']} haven't checked in."
    assert {row["a"], row["b"]} == {"Amina", "Brian"}
    assert row["reasons"][0]["message"] == absent
    assert shown["tables"][0]["idle_reason"] == f"Next would be {row['a']} v {row['b']}, but: {absent}"
    # A player resting: the queue says who, how long, and until when.
    other = started(staff, club, hall, [["Amina"], ["Chege"]], tournament="Veterans Cup")
    send(staff, other, one)
    busy = board(staff, game["cup"])
    assert [reason["code"] for reason in busy["queue"][0]["reasons"]] == ["player_busy", "not_checked_in"]
    assert busy["tables"][0]["held_by"] == "Veterans Cup: Singles"
    drawing.record_result(other["match"], other["match"].entry_a, games=[(11, 5)] * 3)
    resting = board(staff, game["cup"])["queue"][0]["reasons"]
    assert [reason["code"] for reason in resting] == ["not_checked_in", "resting"]
    assert resting[1]["until"] is not None and "Amina finished a match" in resting[1]["message"]
    # Nothing left to play: the table says so.
    done = board(staff, other["cup"])
    assert done["queue"] == []
    assert done["tables"][0]["idle_reason"] == "No match is waiting to be played."


def test_a_knockout_counts_the_matches_still_waiting_for_an_earlier_result(staff, club, hall):
    game = started(staff, club, hall, [["Amina"], ["Brian"], ["Chege"], ["Daudi"]])
    shown = board(staff, game["cup"])
    assert (len(shown["queue"]), shown["to_come"]) == (2, 1)
    assert {row["label"] for row in shown["queue"]} == {"Semi-final"}
    one, two = tables(hall)
    semis = [m for m in matches_of(game) if m.round == 1]
    for semi, table in zip(semis, (one, two), strict=True):
        send(staff, {**game, "match": semi}, table)
    shown = board(staff, game["cup"])
    assert shown["queue"] == [] and [table["free"] for table in shown["tables"]] == [False, False]
    assert shown["tables"][0]["playing"]["match_id"] == str(semis[0].id)
    drawing.record_result(semis[0], semis[0].entry_a, games=[(11, 5)] * 3)
    idle = board(staff, game["cup"])["tables"][0]["idle_reason"]
    assert idle == "Nothing can be played yet: 1 match waits for an earlier result."
    # The final's wait starts when its second side is known.
    drawing.record_result(semis[1], semis[1].entry_a, games=[(11, 5)] * 3)
    final = Match.objects.get(draw=semis[0].draw, round=2)
    assert final.ready_since is not None and final.ready_since >= semis[0].ready_since


def test_a_suggestion_is_checked_again_when_it_is_sent(staff, club, hall):
    one, two = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    shown = board(staff, game["cup"])
    assert shown["queue"][0]["suggested_table"] == "Table 1"
    # Between the board being read and Send being pressed, Amina is sent out in another tournament.
    other = started(staff, club, hall, [["Amina"], ["Chege"]], tournament="Veterans Cup")
    send(staff, other, two)
    refused = send(staff, game, one, expect=409)
    assert (refused["code"], refused["message"]) == ("player_busy", "Amina is playing on Table 2.")
    assert not Reservation.objects.filter(match=game["match"]).exists()


def test_automatic_dispatch_sends_ready_matches_and_never_sets_a_check_aside(staff, club, hall):
    game = league(staff, club, hall, ["Amina", "Brian", "Chege", "Daudi"])
    assert run(staff, game["cup"])["tables"][0]["free"]  # off: looking sends nothing
    shown = auto(staff, game["cup"])
    assert shown["auto_dispatch"] is True
    assert [table["free"] for table in shown["tables"]] == [False, False]
    sent = list(Reservation.objects.order_by("created_at"))
    assert [(r.automatic, r.overrides) for r in sent] == [(True, []), (True, [])]
    assert Hold.objects.filter(active=True, user__isnull=False).count() == 4
    # A result frees a table, but everybody left to play has just played: rest is respected.
    first = sent[0].match
    drawing.record_result(first, first.entry_a, games=[(11, 5)] * 3)
    assert Reservation.objects.filter(status="active").count() == 1
    # The second result frees the other table. Every match left has a player who has just played.
    Hold.objects.filter(active=False).update(released_at=timezone.now() - timedelta(minutes=11))
    drawing.record_result(sent[1].match, sent[1].match.entry_a, games=[(11, 5)] * 3)
    assert not Reservation.objects.filter(status="active").exists()
    reasons = [row["reasons"][0]["code"] for row in board(staff, game["cup"])["queue"]]
    assert reasons == ["resting"] * 4
    # When the rest is over, the open board's next look sends the next two matches.
    Hold.objects.filter(active=False).update(released_at=timezone.now() - timedelta(minutes=11))
    run(staff, game["cup"])
    active = Reservation.objects.filter(status="active")
    assert [r.automatic for r in active] == [True, True]
    people = list(Hold.objects.filter(active=True, user__isnull=False).values_list("user_id", flat=True))
    assert len(people) == len(set(people)) == 4


def test_automatic_dispatch_leaves_unchecked_in_and_called_back_matches_to_people(staff, club, hall):
    late = started(staff, club, hall, [["Amina"], ["Brian"]], checked_in=False)
    auto(staff, late["cup"])
    assert not Reservation.objects.exists()
    for entry in Entry.objects.filter(event_id=late["event"]["id"]):
        staff.post(url(late["cup"], event=late["event"]) + f"entries/{entry.id}/check-in/", {}, format="json")
    assert run(staff, late["cup"])["tables"][0]["playing"]["a"] in ("Amina", "Brian")
    # Staff call it back: it is not sent straight out again.
    recall(staff, late)
    shown = run(staff, late["cup"])
    assert not Reservation.objects.filter(status="active").exists()
    assert (shown["queue"][0]["state"], shown["queue"][0]["reasons"][0]["code"]) == ("waiting", "called_back")
    one, _ = tables(hall)
    send(staff, late, one)  # by hand it goes
    assert auto(staff, late["cup"], enabled=False)["auto_dispatch"] is False
    assert Tournament.objects.get(pk=late["cup"]["id"]).auto_dispatch is False


def test_the_board_is_for_competition_staff(staff, club, hall, client):
    from .helpers import logged_in, make_user

    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    player = logged_in(make_user("visitor@example.com", display_name="Visitor"))
    assert player.get(url(game["cup"]) + "dispatch/").status_code == 403
    assert (
        player.post(url(game["cup"]) + "dispatch/auto/", {"enabled": True}, format="json").status_code == 403
    )
    assert player.post(url(game["cup"]) + "dispatch/run/", {}, format="json").status_code == 403
    assert Tournament.objects.get(pk=game["cup"]["id"]).auto_dispatch is False
