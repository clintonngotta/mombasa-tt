"""Jumbles: a mixed-doubles round robin with a new partner every round (TASK-100)."""

from collections import Counter

import pytest

from competitions import drawing, jumbles
from competitions.models import Entry, Match

from .helpers import logged_in, make_user
from .test_draws import draw_url
from .test_entries import enter
from .test_reservations import person
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db

MEN = ["Amani", "Baraka", "Chege", "Daudi"]
WOMEN = ["Wanjiru", "Xenia", "Yasmin", "Zawadi"]


def jumbles_event(staff, club, men=MEN, women=WOMEN, hall="Makadara Hall", scope="local", publisher=None):
    tournament = make_tournament(staff, club, make_venue(staff, club, name=hall), scope=scope)
    tournament = add_event(staff, tournament, name="Jumbles", kind="jumbles", format="round_robin")
    tournament = do(publisher or staff, tournament, "publish")
    event = tournament["events"][0]
    for name in men:
        enter(staff, tournament, event, player_ids=[str(person(name).id)], pool="men")
    for name in women:
        enter(staff, tournament, event, player_ids=[str(person(name).id)], pool="women")
    return tournament, event


def preview(staff, tournament, event, expect=200, rng_seed=7) -> dict:
    response = staff.post(draw_url(tournament, event, "preview"), {"rng_seed": rng_seed}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def names(side) -> tuple[str, str]:
    man, woman = (player["display_name"] for player in side["entry"]["players"])
    return man, woman


def test_a_jumbles_event_is_a_round_robin_of_players_entered_alone_in_a_pool(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    refused = staff.post(
        url(tournament, event=False), {"name": "J", "kind": "jumbles", "format": "knockout"}, format="json"
    )
    assert refused.status_code == 400 and "format" in refused.json()["fields"]
    tournament = add_event(
        staff, tournament, name="J", kind="jumbles", format="round_robin", seeding="rating"
    )
    event = tournament["events"][0]
    assert event["seeding"] == "none"
    tournament = do(staff, tournament, "publish")

    amani, wanjiru = person("Amani"), person("Wanjiru")
    assert enter(staff, tournament, event, 400, player_ids=[str(amani.id)])["fields"]["pool"]
    pair = [str(amani.id), str(wanjiru.id)]
    assert "player_ids" in enter(staff, tournament, event, 400, player_ids=pair, pool="men")["fields"]
    made = enter(staff, tournament, event, player_ids=[str(amani.id)], pool="men")
    assert made["pool"] == "men" and made["status"] == "accepted"


def test_every_round_pairs_each_man_with_a_new_woman(staff, club):
    tournament, event = jumbles_event(staff, club)
    draw = preview(staff, tournament, event)["preview"]
    assert len(draw["places"]) == 8 and {p["group"] for p in draw["places"]} == {1}
    matches = draw["matches"]
    assert Counter(m["round"] for m in matches) == {1: 2, 2: 2, 3: 2}

    partners: dict[str, set] = {}
    opponents: Counter = Counter()
    for round_number in (1, 2, 3):
        playing = []
        for match in (m for m in matches if m["round"] == round_number):
            sides = [names(match["a"]), names(match["b"])]
            for man, woman in sides:
                assert man in MEN and woman in WOMEN
                partners.setdefault(man, set()).add(woman)
                playing += [man, woman]
            opponents[frozenset((sides[0][0], sides[1][0]))] += 1
        assert sorted(playing) == sorted(MEN + WOMEN)  # everybody plays once a round
    # Three rounds, three different partners for every man, and each man meets each other man once.
    assert all(len(found) == 3 for found in partners.values())
    assert len(opponents) == 6 and set(opponents.values()) == {1}

    # Pairings are the draw's: they aren't entries anybody sees, and drawing again replaces them.
    listed = staff.get(url(tournament, event=event) + "entries/").json()["results"]
    assert len(listed) == 8 and all(entry["status"] == "accepted" for entry in listed)
    assert Entry.objects.filter(status="pairing").count() == 12
    preview(staff, tournament, event, rng_seed=8)
    assert Entry.objects.filter(status="pairing").count() == 12
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
    viewer = logged_in(person("Onlooker"))
    shown = viewer.get(draw_url(tournament, event)).json()["published"]
    assert len(shown["matches"]) == 6 and shown["matches"][0]["a"]["entry"]["title"].count(" / ") == 1


def test_uneven_pools_cannot_be_drawn_and_an_odd_pool_sits_one_pair_out(staff, club):
    tournament, event = jumbles_event(staff, club, MEN[:3], WOMEN[:2])
    refused = preview(staff, tournament, event, expect=409)
    assert refused["code"] == "jumbles_unbalanced" and "3 men and 2 women" in refused["message"]

    tournament, event = jumbles_event(
        staff, club, ["Eli", "Fumo", "Gari"], ["Hawa", "Imani", "Jane"], hall="Tononoka Hall"
    )
    matches = preview(staff, tournament, event)["preview"]["matches"]
    assert Counter(m["round"] for m in matches) == {1: 1, 2: 1, 3: 1}
    partners: dict[str, set] = {}
    for match in matches:
        for man, woman in (names(match["a"]), names(match["b"])):
            assert woman not in partners.setdefault(man, set())
            partners[man].add(woman)


def played(staff, tournament, event) -> list[Match]:
    """Draw, publish and start the event, every pairing checked in."""
    preview(staff, tournament, event)
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    for entry in Entry.objects.filter(event_id=event["id"], status="accepted"):
        staff.post(url(tournament, event=event) + f"entries/{entry.id}/check-in/", {}, format="json")
    do(staff, tournament, "start")
    do(staff, tournament, "start", event=event)
    return list(Match.objects.filter(draw__event_id=event["id"]).prefetch_related("entry_a__players"))


def test_standings_rank_each_player_by_the_points_they_scored(staff, club):
    tournament, event = jumbles_event(staff, club)
    star = person("Amani")
    matches = played(staff, tournament, event)
    expected = Counter()
    for match in matches:
        assert jumbles.checked_in(match.entry_a) and jumbles.checked_in(match.entry_b)
        a_has_star = star.id in {p.user_id for p in match.entry_a.players.all()}
        b_has_star = star.id in {p.user_id for p in match.entry_b.players.all()}
        a_wins = a_has_star or not b_has_star
        games = [[11, 6], [11, 8], [11, 9]] if a_wins else [[6, 11], [8, 11], [9, 11]]
        drawing.record_result(match, match.entry_a if a_wins else match.entry_b, games=games, actor=None)
        for entry, points in ((match.entry_a, [g[0] for g in games]), (match.entry_b, [g[1] for g in games])):
            for place in entry.players.all():
                expected[place.user_id] += sum(points)

    table = staff.get(url(tournament, event=event) + "standings/").json()
    (group,) = table["groups"]
    assert group["complete"] is True
    rows = group["rows"]
    assert [row["rank"] for row in rows] == sorted(row["rank"] for row in rows)
    amani = next(row for row in rows if row["entry"]["players"][0]["display_name"] == "Amani")
    assert (amani["rank"], amani["won"], amani["played"], amani["points_won"]) == (1, 3, 3, 99)
    for row in rows:
        user = Entry.objects.get(pk=row["entry"]["id"]).players.get().user_id
        assert row["points_won"] == expected[user]
    # Equal totals share a rank.
    for before, after in zip(rows, rows[1:], strict=False):
        if before["points_won"] == after["points_won"] and before["won"] == after["won"]:
            same = before["points_won"] - before["points_lost"] == after["points_won"] - after["points_lost"]
            assert (before["rank"] == after["rank"]) is same
    assert table["placements"][0]["label"] == "Winner"
    # Whoever else scored as much, as often, is a joint winner.
    winners = {row["entry"]["id"] for row in rows if row["rank"] == 1}
    assert amani["entry"]["id"] in winners
    assert {entry["id"] for entry in table["placements"][0]["entries"]} == winners


def test_jumbles_counts_for_doubles_ratings_only_at_an_official_tournament(staff, club):
    from ratings.models import Rating, RatingEvent

    from .test_ratings import work

    local, local_event = jumbles_event(staff, club)
    for match in played(staff, local, local_event):
        drawing.record_result(match, match.entry_a, games=[[11, 6], [11, 8], [11, 9]], actor=None)
    work()
    assert not RatingEvent.objects.exists()

    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    root = logged_in(make_user("root@example.com", is_superuser=True, is_staff=True))
    regional, event = jumbles_event(
        staff,
        club,
        ["Eli", "Fumo"],
        ["Hawa", "Imani"],
        hall="Tononoka Hall",
        scope="regional",
        publisher=root,
    )
    assert regional["approval_status"] == "approved"
    first, *rest = played(staff, regional, event)
    drawing.record_result(first, first.entry_a, games=[[11, 6], [11, 8], [11, 9]], actor=None)
    work()
    for place in first.entry_a.players.all():
        assert Rating.objects.get(user_id=place.user_id, discipline="doubles").rating == 1016.0
    for place in first.entry_b.players.all():
        assert Rating.objects.get(user_id=place.user_id, discipline="doubles").rating == 984.0
    assert not Rating.objects.filter(discipline="singles").exists()
    assert RatingEvent.objects.filter(match=first).count() == 4
