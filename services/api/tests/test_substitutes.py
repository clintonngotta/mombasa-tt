"""A player who leaves part-way is replaced by someone else (TASK-155, user request 2026-11-28).

The place carries on (user decision, 2026-11-28): the newcomer plays the matches left, the place keeps
its results so far, and the matches already played stay with the people who played them.
"""

import pytest

from competitions.models import Entry, EntryPlayer, Match, MatchDayLog
from outbox import service as outbox
from ratings.models import RatingEvent
from reservations import service as reservations

from .helpers import logged_in, make_user
from .test_disqualification import staff_member
from .test_official_results import GAMES, enter, fresh, hall, knockout  # noqa: F401
from .test_reservations import person, started, tables
from .test_standings import standings_of
from .test_ties import cup, hand_in, picks, tie  # noqa: F401
from .test_tournaments import url

pytestmark = pytest.mark.django_db


def swap(client, game, entry_id, leaving, joining, expect=200, **body) -> dict:
    path = url(game["cup"], event=game["event"]) + f"entries/{entry_id}/substitute/"
    sent = {"leaving_user_id": str(leaving.id), "joining_user_id": str(joining.id), **body}
    response = client.post(path, sent, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def round_robin(staff, club, hall, names=("Amina", "Brian", "Chege", "Daudi"), **event) -> tuple[dict, list]:  # noqa: F811
    game = started(
        staff,
        club,
        hall,
        [[name] if isinstance(name, str) else list(name) for name in names],
        format="round_robin",
        **event,
    )
    return game, list(
        Match.objects.filter(draw__event_id=game["event"]["id"]).select_related("entry_a", "entry_b")
    )


def entry_of(name: str, event_id) -> Entry:
    return Entry.objects.get(event_id=event_id, players__user__display_name=name, players__live=True)


def test_a_swapped_in_player_carries_on_the_place_and_the_past_stays_with_who_played(staff, club, hall):  # noqa: F811
    game, matches = round_robin(staff, club, hall)
    event_id = game["event"]["id"]
    amina, brian = entry_of("Amina", event_id), entry_of("Brian", event_id)
    played = next(m for m in matches if {m.entry_a_id, m.entry_b_id} == {amina.id, brian.id})
    enter(
        staff,
        game,
        played,
        amina,
        games=GAMES if played.entry_a_id == amina.id else [[b, a] for a, b in GAMES],
    )
    zawadi = person("Zawadi")

    shown = swap(staff, game, amina.id, person("Amina"), zawadi, reason="Flight home")

    assert shown["status"] == "accepted" and [p["id"] for p in shown["players"]] == [str(zawadi.id)]
    old = Entry.objects.get(pk=amina.id)
    assert (old.status, str(old.replaced_by_id), old.reason) == ("replaced", shown["id"], "Flight home")
    assert not EntryPlayer.objects.filter(entry=old, live=True).exists()
    # The match Amina played stays hers; the two she had left are Zawadi's now.
    assert fresh(played).winner_id == amina.id and amina.id in (
        fresh(played).entry_a_id,
        fresh(played).entry_b_id,
    )
    left = Match.objects.filter(draw__event_id=event_id, status=Match.Status.SCHEDULED)
    assert left.filter(entry_a_id=amina.id).count() + left.filter(entry_b_id=amina.id).count() == 0
    assert sum(1 for m in left if shown["id"] in (str(m.entry_a_id), str(m.entry_b_id))) == 2
    # The group counts Amina's win for the place Zawadi holds now.
    table = standings_of(staff, game["cup"], game["event"])["groups"][0]["rows"]
    row = next(r for r in table if r["entry"]["id"] == shown["id"])
    assert row["match_points"] == 2
    assert MatchDayLog.objects.get(action="player_swapped").reason == "Flight home"
    # Ratings: the played match is Amina's, never Zawadi's.
    while outbox.work():
        pass
    assert set(RatingEvent.objects.filter(match=played).values_list("user__display_name", flat=True)) == {
        "Amina",
        "Brian",
    }


def test_the_winner_of_a_knockout_match_is_replaced_in_the_next_round(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    winner = first.entry_a.players.get().user
    shown = swap(staff, game, first.entry_a_id, winner, person("Zawadi"))
    final = fresh(game["final"])
    assert str(final.entry_a_id if final.feeder_a_id == first.id else final.entry_b_id) == shown["id"]
    # The other semi-final still sends its winner on as usual.
    enter(staff, game, second, second.entry_b, games=[[b, a] for a, b in GAMES])
    final = fresh(game["final"])
    assert {str(final.entry_a_id), str(final.entry_b_id)} == {shown["id"], str(second.entry_b_id)}


def test_in_doubles_the_partner_who_stays_moves_with_the_place(staff, club, hall):  # noqa: F811
    game, _ = round_robin(
        staff, club, hall, names=[("Amina", "Asha"), ("Brian", "Baraka"), ("Chege", "Chao")], kind="doubles"
    )
    pair = entry_of("Amina", game["event"]["id"])
    shown = swap(staff, game, pair.id, person("Amina"), person("Zawadi"))
    assert [p["display_name"] for p in shown["players"]] == ["Zawadi", "Asha"]
    assert (
        EntryPlayer.objects.get(user=person("Asha"), live=True).entry_id
        == Entry.objects.get(pk=shown["id"]).id
    )


def test_a_team_takes_a_new_player_on_its_roster_and_the_captaincy_moves_with_them(staff, tie):  # noqa: F811
    tudor = tie["tudor"]
    captain, *_ = tie["tudor_players"]
    newcomer = make_user("juma@example.com", display_name="Juma")
    shown = swap(staff, tie, tudor["id"], captain, newcomer)
    assert shown["id"] == tudor["id"] and shown["captain_id"] == str(newcomer.id)
    assert "Juma" in [p["display_name"] for p in shown["players"]]
    # A lineup that names the player who leaves must be reset first.
    hand_in(staff, tie, "nyali")
    players = tie["tudor_players"]
    other = make_user("kito@example.com", display_name="Kito")
    hand_in(staff, tie, "tudor", lineup=picks([newcomer, *players[1:]]))
    assert swap(staff, tie, tudor["id"], players[1], other, expect=409)["code"] == "in_lineup"


def test_a_swap_is_refused_while_a_match_is_on_a_table_or_for_someone_already_entered(staff, club, hall):  # noqa: F811
    game, matches = round_robin(staff, club, hall)
    event_id = game["event"]["id"]
    amina = entry_of("Amina", event_id)
    assert (
        swap(staff, game, amina.id, person("Amina"), person("Brian"), expect=409)["code"] == "already_entered"
    )
    assert (
        swap(staff, game, amina.id, person("Brian"), person("Zawadi"), expect=409)["code"] == "not_in_entry"
    )
    hers = next(m for m in matches if amina.id in (m.entry_a_id, m.entry_b_id))
    reservations.dispatch(hers, tables(hall)[0], person("Amina"))
    assert (
        swap(staff, game, amina.id, person("Amina"), person("Zawadi"), expect=409)["code"] == "match_in_play"
    )
    assert Entry.objects.get(pk=amina.id).status == "accepted"


def test_only_competition_staff_swap_players(staff, club, hall):  # noqa: F811
    game, _ = round_robin(staff, club, hall)
    amina = entry_of("Amina", game["event"]["id"])
    member = staff_member(club, "member@example.com")  # a club member with no role
    player = logged_in(person("Amina"))
    outsider = logged_in(make_user("outsider@example.com"))
    for client in (member, player, outsider):
        response = client.post(
            url(game["cup"], event=game["event"]) + f"entries/{amina.id}/substitute/",
            {"leaving_user_id": str(person("Amina").id), "joining_user_id": str(person("Zawadi").id)},
            format="json",
        )
        assert response.status_code in (403, 404)
    assert Entry.objects.get(pk=amina.id).status == "accepted"
