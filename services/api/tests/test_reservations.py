"""Tables and players in one place at a time (REQ-014, EVAL-014, TASK-027). The races run on real
PostgreSQL with one connection per request, like production."""

import threading
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from competitions import drawing, ties
from competitions.models import Entry, Event, Match, Rubber
from facilities.models import Table
from reservations import service as reservations
from reservations.models import Hold, Reservation

from .helpers import logged_in, make_user
from .test_draws import draw_url
from .test_entries import enter
from .test_roles import add_member, create_club
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db


def started(staff, club, venue, names: list[list[str]], *, checked_in=True, **event) -> dict:
    """A tournament in progress with one event whose draw is published. `names` are the players of
    each entry (existing users are reused, so the same person can be in two events)."""
    tournament = make_tournament(staff, club, venue, name=event.pop("tournament", "Coast Open"))
    tournament = add_event(staff, tournament, name=event.pop("name", "Singles"), **event)
    tournament = do(staff, tournament, "publish")
    made = tournament["events"][0]
    for players in names:
        users = [person(name) for name in players]
        entry = enter(staff, tournament, made, player_ids=[str(user.id) for user in users])
        if checked_in:
            staff.post(url(tournament, event=made) + f"entries/{entry['id']}/check-in/", {}, format="json")
    staff.post(draw_url(tournament, made, "preview"), {"rng_seed": 1}, format="json")
    assert staff.post(draw_url(tournament, made, "publish"), {}, format="json").status_code == 200
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=made)
    return {
        "cup": tournament,
        "event": made,
        "match": Match.objects.filter(draw__event_id=made["id"]).first(),
    }


def person(name: str):
    from accounts.models import User

    email = f"{name.lower().replace(' ', '.')}@example.com"
    return User.objects.filter(display_name=name).first() or make_user(email, display_name=name)


def send(client, game, table, expect=200, **body) -> dict:
    path = url(game["cup"], event=game["event"]) + f"matches/{game['match'].id}/dispatch/"
    response = client.post(path, {"table_id": str(table.id), **body}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def recall(client, game, expect=200, reason="Wrong table") -> dict:
    path = url(game["cup"], event=game["event"]) + f"matches/{game['match'].id}/recall/"
    response = client.post(path, {"reason": reason}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def tables(hall) -> list[Table]:
    return list(Table.objects.filter(venue_id=hall["id"]).order_by("position"))


def test_a_match_sent_to_a_table_holds_the_table_and_its_players_until_its_result(staff, club, hall):
    one, two = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    shown = send(staff, game, one)
    assert shown["table"] == "Table 1" and shown["dispatched_at"]
    assert (shown["on_table"]["table"], shown["on_table"]["people"]) == ("Table 1", ["Amina", "Brian"])
    assert shown["can_dispatch"] is True
    states = staff.get(url(game["cup"]) + "tables/").json()
    assert [(t["label"], t["free"], t["held_by"]) for t in states] == [
        ("Table 1", False, "Coast Open: Singles"),
        ("Table 2", True, ""),
    ]
    (held,) = staff.get(url(game["cup"]) + "reservations/").json()
    assert (held["table"], held["a"], held["b"], held["people"]) == (
        "Table 1",
        game["match"].entry_a.players.get().user.display_name,
        game["match"].entry_b.players.get().user.display_name,
        ["Amina", "Brian"],
    )
    assert send(staff, game, two, expect=409)["code"] == "already_on_table"

    # The result releases everything in the transaction that records it.
    match = game["match"]
    drawing.record_result(Match.objects.get(pk=match.pk), match.entry_a, games=[(11, 5)] * 3)
    assert not Hold.objects.filter(active=True).exists()
    reservation = Reservation.objects.get()
    assert (reservation.status, reservation.ending, reservation.released_at is not None) == (
        "released",
        "decided",
        True,
    )
    assert staff.get(url(game["cup"]) + "reservations/").json() == []
    assert all(t["free"] for t in staff.get(url(game["cup"]) + "tables/").json())


def test_a_table_and_a_player_are_never_in_two_places_across_events_and_clubs(staff, club, hall, admin):
    one, two = tables(hall)
    singles = started(staff, club, hall, [["Amina"], ["Brian"]], name="Singles")
    veterans = started(staff, club, hall, [["Amina"], ["Chege"]], name="Veterans", tournament="Veterans Cup")
    send(staff, singles, one)
    # The table is taken, and so is Amina, whichever event asks.
    busy_table = send(staff, veterans, one, expect=409)
    assert busy_table["code"] == "table_busy" and "Coast Open" not in busy_table["message"]
    assert "Singles" in busy_table["message"]
    busy_player = send(staff, veterans, two, expect=409)
    assert (busy_player["code"], busy_player["message"]) == ("player_busy", "Amina is playing on Table 1.")
    # No override reaches exclusivity.
    forced = send(staff, veterans, two, expect=409, overrides=["check_in", "rest"], reason="Running late")
    assert forced["code"] == "player_busy"

    # Another club, another venue: the same person is still one person.
    other_admin = make_user("other.admin@example.com", display_name="Other Admin")
    other_club = create_club(other_admin, name="Nyali TT Club")
    other_staff = logged_in(other_admin)
    other_hall = make_venue(other_staff, other_club, name="Nyali Hall")
    add_table(other_staff, other_club, other_hall, "Table A")
    away = started(other_staff, other_club, other_hall, [["Brian"], ["Daudi"]], tournament="Nyali Open")
    refused = send(other_staff, away, Table.objects.get(label="Table A"), expect=409)
    assert (refused["code"], refused["message"]) == ("player_busy", "Brian is playing on Table 1.")
    # A table of somebody else's venue can't be used at all.
    assert send(other_staff, away, two, expect=409)["code"] == "table_unavailable"
    assert Reservation.objects.count() == 1 and Hold.objects.filter(active=True).count() == 3


def test_check_in_and_rest_are_checked_and_can_be_set_aside_with_a_reason(staff, club, hall):
    one, two = tables(hall)
    game = started(staff, club, hall, [["Amina"], ["Brian"]], checked_in=False)
    absent = send(staff, game, one, expect=409)
    assert absent["code"] == "not_checked_in" and "haven't checked in" in absent["message"]
    assert send(staff, game, one, expect=400, overrides=["check_in"])["code"] == "reason_required"
    shown = send(staff, game, one, overrides=["check_in"], reason="Seen at the table by the referee")
    assert shown["on_table"]["table"] == "Table 1"
    reservation = Reservation.objects.get()
    assert (reservation.overrides, reservation.override_reason) == (
        ["check_in"],
        "Seen at the table by the referee",
    )
    drawing.record_result(game["match"], game["match"].entry_a, games=[(11, 5)] * 3)

    # Amina has just finished: her next match waits out this event's rest (10 minutes by default).
    later = started(staff, club, hall, [["Amina"], ["Chege"]], name="Veterans", tournament="Veterans Cup")
    resting = send(staff, later, two, expect=409)
    assert resting["code"] == "resting" and resting["message"].startswith("Amina finished a match")
    # Nine minutes later still resting; after ten she can play.
    Hold.objects.filter(active=False).update(released_at=timezone.now() - timedelta(minutes=9))
    assert send(staff, later, two, expect=409)["code"] == "resting"
    Hold.objects.filter(active=False).update(released_at=timezone.now() - timedelta(minutes=10, seconds=1))
    assert send(staff, later, two)["on_table"]["people"] == ["Amina", "Chege"]
    recall(staff, later)
    # Rest can be set aside too, with a reason, and being recalled is not having played.
    Hold.objects.filter(active=False).update(released_at=timezone.now())
    assert send(staff, later, two, expect=409)["code"] == "resting"
    send(staff, later, two, overrides=["rest"], reason="Both players asked to go on")
    assert Reservation.objects.filter(status="active").get().overrides == ["rest"]


def test_only_a_ready_match_goes_to_a_table_and_staff_can_call_it_back(staff, club, hall):
    one, _ = tables(hall)
    knockout = started(staff, club, hall, [["A1"], ["A2"], ["A3"], ["A4"]], format="knockout")
    final = Match.objects.get(draw__event_id=knockout["event"]["id"], round=2)
    waiting = send(staff, {**knockout, "match": final}, one, expect=409)
    assert waiting["code"] == "waiting_for_players"

    semi = knockout["match"]
    stranger = logged_in(make_user("stranger@example.com"))
    path = url(knockout["cup"], event=knockout["event"]) + f"matches/{semi.id}/"
    assert stranger.post(path + "dispatch/", {"table_id": str(one.id)}, format="json").status_code == 403
    assert stranger.get(url(knockout["cup"]) + "tables/").status_code == 403
    assert stranger.get(url(knockout["cup"]) + "reservations/").status_code == 403
    assert stranger.get(path).json()["can_dispatch"] is False

    send(staff, knockout, one)
    seen = stranger.get(path).json()
    assert (seen["on_table"]["table"], seen["on_table"]["waiting_for"]) == ("Table 1", [])
    assert stranger.post(path + "recall/", {"reason": "x"}, format="json").status_code == 403
    assert recall(staff, knockout, expect=400, reason="")["fields"]["reason"]
    back = recall(staff, knockout)
    assert back["on_table"] is None and back["table"] == "" and back["dispatched_at"] is None
    assert recall(staff, knockout, expect=409)["code"] == "not_on_table"
    reservation = Reservation.objects.get()
    assert (reservation.ending, reservation.release_reason) == ("recalled", "Wrong table")
    # A decided match goes nowhere.
    drawing.record_result(semi, semi.entry_a, games=[(11, 5)] * 3)
    assert send(staff, knockout, one, expect=409)["code"] == "match_decided"


def test_an_umpire_is_not_sent_to_play_while_their_match_is_on_a_table(staff, club, hall):
    from scoring import service as scoring

    one, two = tables(hall)
    first = started(staff, club, hall, [["Amina"], ["Brian"]], name="Singles")
    second = started(staff, club, hall, [["Chege"], ["Daudi"]], name="Veterans", tournament="Veterans Cup")
    chege = person("Chege")
    add_member(club, chege, "assistant_captain")
    from django.db import transaction

    with transaction.atomic():
        scoring.assign(first["match"], None, chege, person("Chege"))
    send(staff, first, one)
    refused = send(staff, second, two, expect=409)
    assert (refused["code"], refused["message"]) == (
        "player_umpiring",
        "Chege is umpiring a match on Table 1.",
    )
    # And the other way round: a match whose umpire is playing right now isn't sent out.
    recall(staff, first)
    send(staff, second, two)
    assert send(staff, first, one, expect=409)["code"] == "umpire_busy"


def test_a_tie_holds_its_table_throughout_and_its_players_rubber_by_rubber(staff, club, hall):
    from .test_ties import hand_in, picks, team

    one, two = tables(hall)
    tournament = make_tournament(staff, club, hall)
    tournament = add_event(
        staff, tournament, name="Teams", kind="team", format="round_robin", tie_rubbers=["singles"] * 3
    )
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    tudor, tudor_players = team(staff, tournament, event, "Tudor")
    nyali, nyali_players = team(staff, tournament, event, "Nyali")
    for entry in (tudor, nyali):
        staff.post(url(tournament, event=event) + f"entries/{entry['id']}/check-in/", {}, format="json")
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    match = Match.objects.get(draw__event_id=event["id"])
    tie = {"cup": tournament, "event": event, "match": match, "tudor": tudor, "nyali": nyali}
    assert send(staff, tie, one, expect=409)["code"] == "waiting_for_lineups"
    order = ((0,), (1,), (2,))
    hand_in(staff, tie, "tudor", picks(tudor_players, order))
    hand_in(staff, tie, "nyali", picks(nyali_players, order))

    shown = send(staff, tie, one)
    assert shown["on_table"]["people"] == ["Nyali 0", "Tudor 0"]  # the first rubber's players only
    # Somebody playing later in the tie is free for another match meanwhile.
    side = started(staff, club, hall, [["Tudor 1"], ["Extra"]], name="Singles", tournament="Side Cup")
    send(staff, side, two)

    rubbers = list(Rubber.objects.filter(match=match))
    winner = Entry.objects.get(pk=tudor["id"])
    games = [(11, 5)] * 3 if winner.id == match.entry_a_id else [(5, 11)] * 3
    ties.record_rubber(rubbers[0], winner, games=games)
    # Rubber 2 needs Tudor 1, who is on Table 2: the tie keeps its table, holds who it can and says so.
    shown = staff.get(url(tournament, event=event) + f"matches/{match.id}/").json()
    assert shown["on_table"]["people"] == ["Nyali 1"]
    assert shown["on_table"]["waiting_for"] == ["Tudor 1"]
    assert Hold.objects.filter(table=one, active=True).exists()
    # When the side match is decided, the tie gets its player at once.
    drawing.record_result(side["match"], side["match"].entry_a, games=[(11, 5)] * 3)
    shown = staff.get(url(tournament, event=event) + f"matches/{match.id}/").json()
    assert (shown["on_table"]["people"], shown["on_table"]["waiting_for"]) == (["Nyali 1", "Tudor 1"], [])
    ties.record_rubber(rubbers[1], winner, games=games)
    # Two wins of three: the tie is decided and nothing is held any more.
    assert Match.objects.get(pk=match.pk).status == "completed"
    assert not Hold.objects.filter(active=True).exists()
    # Rest follows play: the third rubber wasn't needed, so its players were never held and owe no rest.
    teams = Event.objects.get(pk=event["id"])
    assert not Hold.objects.filter(user=person("Tudor 2")).exists()
    assert reservations.rest_until(person("Tudor 2"), teams) is None
    assert reservations.rest_until(person("Tudor 1"), teams) is not None


def test_a_tie_on_a_table_keeps_its_lineups(staff, club, hall):
    from .test_ties import hand_in, picks, team

    one, _ = tables(hall)
    tournament = make_tournament(staff, club, hall)
    tournament = add_event(
        staff, tournament, name="Teams", kind="team", format="round_robin", tie_rubbers=["singles"] * 3
    )
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    tudor, tudor_players = team(staff, tournament, event, "Tudor")
    nyali, nyali_players = team(staff, tournament, event, "Nyali")
    for entry in (tudor, nyali):
        staff.post(url(tournament, event=event) + f"entries/{entry['id']}/check-in/", {}, format="json")
    staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    match = Match.objects.get(draw__event_id=event["id"])
    tie = {"cup": tournament, "event": event, "match": match, "tudor": tudor, "nyali": nyali}
    order = ((0,), (1,), (2,))
    hand_in(staff, tie, "tudor", picks(tudor_players, order))
    hand_in(staff, tie, "nyali", picks(nyali_players, order))
    send(staff, tie, one)
    reset = url(tournament, event=event) + f"matches/{match.id}/lineup/reset/"
    refused = staff.post(reset, {}, format="json")
    assert (refused.status_code, refused.json()["code"]) == (409, "tie_on_table")
    assert Hold.objects.filter(active=True).count() == 3  # the table and the first rubber's two players
    recall(staff, tie)
    assert staff.post(reset, {}, format="json").status_code == 200


def test_closing_an_event_frees_what_its_matches_held(staff, club, hall):
    one, two = tables(hall)
    first = started(staff, club, hall, [["Amina"], ["Brian"]])
    second = started(staff, club, hall, [["Chege"], ["Daudi"]], tournament="Veterans Cup")
    third = started(staff, club, hall, [["Amina"], ["Chege"]], tournament="Evening Cup")
    send(staff, first, one)
    send(staff, second, two)
    do(staff, first["cup"], "cancel", event=first["event"], reason="Power cut")
    do(staff, second["cup"], "cancel", reason="Power cut")
    assert not Hold.objects.filter(active=True).exists()
    assert set(Reservation.objects.values_list("ending", flat=True)) == {"closed"}
    assert Match.objects.get(pk=first["match"].pk).dispatched_at is None
    # Nobody played, so nobody rests: the table and both players go straight to another tournament.
    send(staff, third, one)
    do(staff, third["cup"], "complete", event=third["event"])
    assert not Hold.objects.filter(active=True).exists()


def test_a_walkover_is_not_play_so_nobody_rests_after_it(staff, club, hall):
    one, _ = tables(hall)
    first = started(staff, club, hall, [["Amina"], ["Brian"]])
    second = started(staff, club, hall, [["Amina"], ["Chege"]], tournament="Veterans Cup")
    send(staff, first, one)
    match = first["match"]
    drawing.record_result(match, match.entry_a, outcome="walkover")
    send(staff, second, one)


def test_somebody_playing_is_not_made_umpire_of_a_match_on_a_table(staff, club, hall):
    from django.db import transaction

    from scoring import service as scoring

    one, two = tables(hall)
    first = started(staff, club, hall, [["Amina"], ["Brian"]])
    second = started(staff, club, hall, [["Chege"], ["Daudi"]], tournament="Veterans Cup")
    chege = person("Chege")
    add_member(club, chege, "assistant_captain")
    send(staff, first, one)
    send(staff, second, two)
    with pytest.raises(reservations.Blocked) as refused, transaction.atomic():
        scoring.assign(first["match"], None, chege, chege)
    assert refused.value.blocker == "umpire_busy"
    # Once their own match is off its table they can take it.
    recall(staff, second)
    with transaction.atomic():
        scoring.assign(first["match"], None, chege, chege)


def _race(requests) -> list[tuple[int, str]]:
    """Run the requests at the same instant, each on its own database connection."""
    barrier = threading.Barrier(len(requests))
    replies: list[tuple[int, str]] = []

    def run(request):
        try:
            barrier.wait()
            response = request()
            replies.append((response.status_code, response.json().get("code", "")))
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(request,)) for request in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return replies


@pytest.mark.django_db(transaction=True)
def test_a_hundred_races_for_a_shared_player_and_a_shared_table_never_double_reserve():
    """EVAL-014: two matches sharing a player sent to two tables at once, and two matches with nobody
    in common sent to one table at once, fifty rounds each. Exactly one wins every time."""
    admin = make_user("admin@example.com", display_name="Club Admin")
    club = create_club(admin)
    staff = logged_in(admin)
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    one, two = Table.objects.filter(venue_id=venue["id"]).order_by("position")
    singles = started(staff, club, venue, [["Amina"], ["Brian"]], name="Singles")
    veterans = started(staff, club, venue, [["Amina"], ["Chege"]], name="Veterans", tournament="Veterans Cup")
    juniors = started(staff, club, venue, [["Daudi"], ["Esther"]], name="Juniors", tournament="Junior Cup")
    cache.clear()
    clients = [logged_in(admin), logged_in(admin)]

    def dispatching(client, game, table):
        path = url(game["cup"], event=game["event"]) + f"matches/{game['match'].id}/dispatch/"
        return lambda: client.post(path, {"table_id": str(table.id)}, format="json")

    def clear():
        for game in (singles, veterans, juniors):
            if Reservation.objects.filter(match=game["match"], status="active").exists():
                recall(staff, game)

    for round_number in range(50):
        # Amina is in both matches; the tables differ.
        replies = _race([dispatching(clients[0], singles, one), dispatching(clients[1], veterans, two)])
        assert sorted(status for status, _ in replies) == [200, 409], (round_number, replies)
        assert {code for status, code in replies if status == 409} == {"player_busy"}
        assert Hold.objects.filter(active=True, user__display_name="Amina").count() == 1
        clear()
        # Nobody in common; the table is the same.
        replies = _race([dispatching(clients[0], singles, one), dispatching(clients[1], juniors, one)])
        assert sorted(status for status, _ in replies) == [200, 409], (round_number, replies)
        assert {code for status, code in replies if status == 409} == {"table_busy"}
        assert Hold.objects.filter(active=True, table=one).count() == 1
        clear()
    # Every reservation that was ever active held its table and its two players exactly once.
    assert Reservation.objects.count() == 100
    assert Hold.objects.count() == 300 and not Hold.objects.filter(active=True).exists()


@pytest.mark.django_db(transaction=True)
def test_the_database_itself_refuses_a_second_hold():
    """Whatever the code above does, the indexes hold the invariant."""
    from django.db import IntegrityError, transaction

    admin = make_user("admin@example.com", display_name="Club Admin")
    club = create_club(admin)
    staff = logged_in(admin)
    venue = make_venue(staff, club)
    add_table(staff, club, venue, "Table 1")
    table = Table.objects.get()
    first = started(staff, club, venue, [["Amina"], ["Brian"]], name="Singles")
    second = started(staff, club, venue, [["Chege"], ["Daudi"]], name="Veterans", tournament="Veterans Cup")
    send(staff, first, table)
    rogue = Reservation.objects.create(match=second["match"], table=table)
    for held in ({"table": table}, {"user": person("Amina")}):
        with pytest.raises(IntegrityError), transaction.atomic():
            Hold.objects.create(reservation=rogue, **held)
    with pytest.raises(IntegrityError), transaction.atomic():
        Hold.objects.create(reservation=rogue)  # neither a table nor a person
