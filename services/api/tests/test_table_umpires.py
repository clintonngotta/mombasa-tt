"""Tournament umpires, table umpires (user request, 2026-11-22) and the next-match recommendation
(REQ-053, EVAL-053, TASK-128)."""

import pytest

from competitions.models import Match, MatchDayLog
from reservations.models import Reservation, TableUmpire
from scoring.models import Scorecard

from .helpers import logged_in, make_user
from .test_control_centre import board, table_on
from .test_reservations import person, send, started, tables
from .test_roles import add_member
from .test_tournaments import url
from .test_umpire_scoring import START, Deck, point

pytestmark = pytest.mark.django_db


@pytest.fixture
def hall(staff, club):
    from .test_venues import add_table, make_venue

    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def eight(letter: str) -> list[list[str]]:
    return [[f"{letter}{n}"] for n in range(1, 9)]


def umpires_url(game) -> str:
    return url(game["cup"]) + "umpires/"


def add_umpire(client, game, user, expect=200) -> list:
    response = client.post(umpires_url(game), {"user_id": str(user.id)}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def set_table(client, game, table, user, expect=200) -> dict:
    body = {"user_id": str(user.id) if user else None}
    response = client.put(url(game["cup"]) + f"tables/{table.id}/umpire/", body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def umpire_of(match: Match):
    card = Scorecard.objects.filter(match=match).select_related("umpire").first()
    return card.umpire if card else None


def round_one(game) -> list[Match]:
    return list(
        Match.objects.filter(
            draw__event_id=game["event"]["id"],
            round=1,
            status=Match.Status.SCHEDULED,
            entry_a__isnull=False,
            entry_b__isnull=False,
        )
        .select_related("entry_a", "entry_b")
        .order_by("position")
    )


def players(match: Match) -> list:
    return [place.user for entry in (match.entry_a, match.entry_b) for place in entry.players.all()]


def test_staff_build_the_umpire_list_from_members_and_entrants_only(staff, club, hall):
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    member = person("Mwanaisha Member")
    add_member(club, member)
    outsider = person("Otieno Outsider")
    found = staff.get(umpires_url(game) + "candidates/", {"search": ""}).json()
    names = {person["display_name"] for person in found}
    assert {"Amina", "Brian", "Mwanaisha Member"} <= names and "Otieno Outsider" not in names
    assert add_umpire(staff, game, outsider, expect=409)["code"] == "not_eligible"
    amina = round_one(game)[0].entry_a.players.get().user
    roster = add_umpire(staff, game, amina)
    assert [(row["display_name"], row["entered"], row["table"]) for row in roster] == [
        (amina.display_name, True, "")
    ]
    # Once listed, they are offered for any match and no longer a candidate.
    offered = staff.get(umpires_url(game) + "candidates/").json()
    assert amina.display_name not in {p["display_name"] for p in offered}
    assert MatchDayLog.objects.filter(action=MatchDayLog.Action.UMPIRE_LISTED).count() == 1


def test_only_the_hosts_competition_staff_manage_umpires(staff, club, hall):
    game = started(staff, club, hall, [["Amina"], ["Brian"]])
    one, _ = tables(hall)
    member = make_user("plain.member@example.com")
    add_member(club, member)
    for client in (logged_in(member), logged_in(make_user("someone@example.com"))):
        assert client.get(umpires_url(game)).status_code in (403, 404)
        assert client.get(umpires_url(game) + "candidates/").status_code in (403, 404)
        added = client.post(umpires_url(game), {"user_id": str(member.id)}, format="json")
        assert added.status_code in (403, 404)
        put = client.put(url(game["cup"]) + f"tables/{one.id}/umpire/", {"user_id": None}, format="json")
        assert put.status_code in (403, 404)
    assert not TableUmpire.objects.exists()


def test_a_table_umpire_takes_every_match_sent_to_their_table(staff, club, hall):
    game = started(staff, club, hall, eight("A"), best_of=3)
    one, _ = tables(hall)
    zuri = person("Zuri Umpire")
    add_member(club, zuri)  # no scoring role: being on the list is enough
    add_umpire(staff, game, zuri)
    # Not on the list: refused.
    stranger = person("Not Listed")
    add_member(club, stranger)
    assert set_table(staff, game, one, stranger, expect=409)["code"] == "not_listed"
    shown = table_on(set_table(staff, game, one, zuri), "Table 1")
    assert shown["table_umpire"]["name"] == "Zuri Umpire"
    first = round_one(game)[0]
    send(staff, {**game, "match": first}, one)
    assert umpire_of(first) == zuri
    assert table_on(board(staff, game["cup"]), "Table 1")["umpire"] == "Zuri Umpire"
    # The umpire sees it among the matches they score.
    mine = logged_in(zuri).get("/api/v1/me/scorecards/").json()["results"]
    assert [card["match_id"] for card in mine] == [str(first.id)]


def test_a_table_umpire_playing_in_the_match_or_elsewhere_is_skipped(staff, club, hall):
    game = started(staff, club, hall, eight("B"), best_of=3)
    one, two = tables(hall)
    first, second, *_ = round_one(game)
    player = players(first)[0]
    add_umpire(staff, game, player)
    set_table(staff, game, one, player)
    # Their own match on their own table: it goes out, without them as its umpire.
    send(staff, {**game, "match": first}, one)
    assert umpire_of(first) is None
    # Their table is busy with their match; give them table 2 while they play: nothing is forced.
    set_table(staff, game, two, player)
    send(staff, {**game, "match": second}, two)
    assert umpire_of(second) is None
    assert Reservation.objects.filter(match=second, status=Reservation.Status.ACTIVE).exists()


def test_changing_the_table_umpire_moves_the_waiting_match_but_not_one_being_scored(staff, club, hall):
    game = started(staff, club, hall, eight("C"), best_of=3)
    one, two = tables(hall)
    first, second, *_ = round_one(game)
    zuri, yusuf = person("Zuri"), person("Yusuf")
    for user in (zuri, yusuf):
        add_member(club, user)
        add_umpire(staff, game, user)
    set_table(staff, game, one, zuri)
    set_table(staff, game, two, zuri)  # one table per umpire: Zuri moves to table 2
    assert list(TableUmpire.objects.values_list("table_id", flat=True)) == [two.id]
    set_table(staff, game, one, yusuf)
    send(staff, {**game, "match": first}, one)
    send(staff, {**game, "match": second}, two)
    assert (umpire_of(first), umpire_of(second)) == (yusuf, zuri)
    # Zuri starts scoring table 2; Yusuf's match hasn't started.
    as_zuri = logged_in(zuri)
    deck = Deck(as_zuri, Scorecard.objects.get(match=second).id)
    deck.send(START, point("a"))
    set_table(staff, game, one, zuri)  # Zuri moves back to table 1; table 2's match keeps Zuri
    assert umpire_of(first) == zuri and umpire_of(second) == zuri
    set_table(staff, game, two, yusuf)  # the match in play on table 2 keeps its umpire
    assert umpire_of(second) == zuri
    assert MatchDayLog.objects.filter(action=MatchDayLog.Action.TABLE_UMPIRE).count() == 5


def test_taking_an_umpire_off_the_list_takes_back_matches_nobody_started(staff, club, hall):
    game = started(staff, club, hall, [["D1"], ["D2"], ["D3"], ["D4"]], best_of=3)
    one, _ = tables(hall)
    first = round_one(game)[0]
    zuri = person("Zuri Off")
    add_member(club, zuri)
    add_umpire(staff, game, zuri)
    set_table(staff, game, one, zuri)
    send(staff, {**game, "match": first}, one)
    assert umpire_of(first) == zuri
    response = staff.delete(umpires_url(game) + f"{zuri.id}/")
    assert response.status_code == 200 and response.json() == []
    assert umpire_of(first) is None and not TableUmpire.objects.exists()
    assert staff.delete(umpires_url(game) + f"{zuri.id}/").status_code == 404


def finish(deck: Deck) -> None:
    deck.send(START, *[point("a")] * 11)
    deck.send(*[point("a")] * 11)


def test_the_next_match_is_recommended_at_the_winning_point_and_nothing_is_sent(staff, club, hall):
    game = started(staff, club, hall, eight("E"), best_of=3)
    one, _ = tables(hall)
    first = round_one(game)[0]
    zuri = person("Zuri Next")
    add_member(club, zuri)
    add_umpire(staff, game, zuri)
    set_table(staff, game, one, zuri)
    send(staff, {**game, "match": first}, one)
    deck = Deck(logged_in(zuri), Scorecard.objects.get(match=first).id)
    deck.send(START, *[point("a")] * 11, *[point("a")] * 10)
    assert table_on(board(staff, game["cup"]), "Table 1")["next_up"] is None  # one point short
    deck.send(point("a"))
    reservations = Reservation.objects.count()
    shown = table_on(board(staff, game["cup"]), "Table 1")
    following = shown["next_up"]
    assert following and following["table"] == "Table 1"
    nxt = Match.objects.get(pk=following["match_id"])
    assert not set(players(nxt)) & set(players(first))
    # A recommendation only: nothing is held, sent or assigned, and the result isn't confirmed.
    assert Reservation.objects.count() == reservations and nxt.dispatched_at is None
    assert umpire_of(nxt) is None and Match.objects.get(pk=first.pk).status == "scheduled"
    # The umpire hears of it after confirming; nobody else may ask about their sheet.
    path = f"/api/v1/scorecards/{deck.path.split('/')[-2]}/next/"
    assert logged_in(make_user("nosy@example.com")).get(path).status_code == 404
    deck.confirm()
    told = logged_in(zuri).get(path).json()
    assert told["next"]["table"] == "Table 1" and told["next"]["match_id"]
    # With nothing switched on, it was only recommended; once sent there, it is theirs to score.
    if not told["on_table"]:
        send(staff, {**game, "match": Match.objects.get(pk=told["next"]["match_id"])}, one)
        told = logged_in(zuri).get(path).json()
    assert told["on_table"] is True and told["scorecard_id"]
