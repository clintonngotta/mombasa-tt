"""A table set aside for a queued match, and staff's list of who umpires each match (TASK-153).

Staff choose a table for a match before it goes out, even while that table is busy: the match waits for
it, no other match in the queue takes it, and it takes the table's umpire at once. Staff also see every
match still to be played with its umpire, and which are still waiting for one.
"""

import pytest

from competitions.models import Match, MatchDayLog
from reservations.models import Reservation

from .helpers import logged_in
from .test_reservations import person, send, started, tables
from .test_roles import add_member
from .test_table_umpires import add_umpire, eight, hall, round_one, set_table, umpire_of  # noqa: F401
from .test_tournaments import url

pytestmark = pytest.mark.django_db


def hold(client, game, match, table, expect=200) -> dict:
    path = url(game["cup"], event=game["event"]) + f"matches/{match.id}/hold-table/"
    body = {"table_id": str(table.id) if table else None}
    response = client.post(path, body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def queued(shown: dict, match: Match) -> dict:
    return next(row for row in shown["queue"] if row["match_id"] == str(match.id))


def umpiring(client, game, expect=200, **query) -> dict:
    response = client.get(url(game["cup"]) + "umpiring/", query)
    assert response.status_code == expect, response.json()
    return response.json()


def test_a_match_waits_for_the_table_held_for_it_and_no_other_match_takes_that_table(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, eight("H"), best_of=3)
    one, two = tables(hall)
    first, second, third, fourth = round_one(game)
    send(staff, {**game, "match": first}, one)

    # Table 2 is free and set aside for the fourth match: the second, ahead of it, doesn't get it.
    shown = hold(staff, game, fourth, two)
    assert queued(shown, fourth)["held_table"] == "Table 2"
    assert queued(shown, fourth)["suggested_table"] == "Table 2"
    assert queued(shown, second)["state"] == "waiting"
    assert [r["code"] for r in queued(shown, second)["reasons"]] == ["no_free_table"]

    # Table 1 is busy: the third match held for it waits for it, whatever else frees up.
    shown = hold(staff, game, third, one)
    assert queued(shown, third)["state"] == "waiting"
    assert queued(shown, third)["reasons"][0] == {
        "code": "held_table_busy",
        "message": "It waits for Table 1.",
        "until": None,
    }

    # Sending it out, by hand or automatically, frees what was set aside.
    staff.post(url(game["cup"]) + "dispatch/auto/", {"enabled": True}, format="json")
    on_two = Reservation.objects.get(table=two, status=Reservation.Status.ACTIVE)
    assert on_two.match_id == fourth.id
    assert Match.objects.get(pk=fourth.pk).held_table_id is None
    assert Match.objects.get(pk=second.pk).dispatched_at is None

    # A match already on a table is moved, not held; a table of another venue isn't offered.
    assert hold(staff, game, first, two, expect=409)["code"] == "already_on_table"
    assert MatchDayLog.objects.filter(action=MatchDayLog.Action.TABLE_HELD).count() == 2


def test_a_held_match_takes_the_tables_umpire_at_once_and_follows_a_change(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, eight("J"), best_of=3)
    one, _ = tables(hall)
    first, second, *_ = round_one(game)
    zuri, yusuf = person("Zuri Held"), person("Yusuf Held")
    for user in (zuri, yusuf):
        add_member(club, user)
        add_umpire(staff, game, user)
    set_table(staff, game, one, zuri)
    send(staff, {**game, "match": first}, one)

    shown = hold(staff, game, second, one)
    assert umpire_of(second) == zuri
    assert queued(shown, second)["umpire"] == "Zuri Held"
    # Zuri sees it on their page before it goes out.
    mine = logged_in(zuri).get("/api/v1/me/scorecards/").json()["results"]
    assert str(second.id) in [card["match_id"] for card in mine]

    # The table changes umpire: the match waiting for it follows.
    set_table(staff, game, one, yusuf)
    assert umpire_of(second) == yusuf
    # Let go of the table: it goes to any table again and keeps its umpire.
    hold(staff, game, second, None)
    assert Match.objects.get(pk=second.pk).held_table_id is None
    assert umpire_of(second) == yusuf


def test_staff_see_who_umpires_each_match_and_which_still_wait_for_one(staff, club, hall):  # noqa: F811
    game = started(staff, club, hall, eight("K"), best_of=3)
    one, _ = tables(hall)
    first, second, *_ = round_one(game)
    listed = umpiring(staff, game)
    assert listed["count"] == 4 and listed["totals"] == {"assigned": 0, "unassigned": 4}
    assert {row["status"] for row in listed["results"]} == {"unassigned"}

    zuri = person("Zuri Lister")
    add_member(club, zuri)
    add_umpire(staff, game, zuri)
    set_table(staff, game, one, zuri)
    hold(staff, game, second, one)

    given = umpiring(staff, game, umpire="assigned")
    assert [(r["match_id"], r["umpire_name"], r["held_table"]) for r in given["results"]] == [
        (str(second.id), "Zuri Lister", "Table 1")
    ]
    waiting = umpiring(staff, game, umpire="unassigned", page_size=2)
    assert waiting["count"] == 3 and len(waiting["results"]) == 2 and waiting["next"]
    assert waiting["totals"] == {"assigned": 1, "unassigned": 3}
    assert umpiring(staff, game, umpire="everyone", expect=400)

    # Only the host's competition staff: a plain member, or the umpire, can't read it.
    member = person("Plain Member")
    add_member(club, member)
    assert umpiring(logged_in(member), game, expect=403)["code"] == "permission_denied"
    assert umpiring(logged_in(zuri), game, expect=403)["code"] == "permission_denied"
