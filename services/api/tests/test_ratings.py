"""Rating ledgers (REQ-016, EVAL-016, TASK-030): the Elo arithmetic against numbers worked out by
hand, what is and isn't rated, the ledger's order, and a correction's replay against a clean rebuild."""

import pytest
from django.db import transaction

from competitions.models import Entry, Match, OfficialResult
from organizations.models import Membership, Organization
from outbox import service as outbox
from profiles.models import PlayerProfile
from ratings import elo, service
from ratings.models import Rating, RatingEvent

from .helpers import logged_in, make_user
from .test_official_results import GAMES, LOST, correct, enter, fresh, hall, knockout  # noqa: F401
from .test_reservations import person, started
from .test_ties import begin, cup, decide, tie  # noqa: F401
from .test_tournaments import url

pytestmark = pytest.mark.django_db

# Worked by hand from REQ-016, not with the code under test.
# 1100 v 1000: the difference is 100, 10^(100/400) = 10^0.25 = 1.7782794100389228.
E_HIGHER = 0.6400649998028851  # 1 / (1 + 1/1.7782794100389228)
E_LOWER = 0.35993500019711494  # 1 / (1 + 1.7782794100389228)
WIN_AS_HIGHER = 11.517920006307678  # 32 x (1 - 0.6400649998028851)
WIN_AS_LOWER = 20.48207999369232  # 32 x (1 - 0.35993500019711494)
# 984 v 1016: the difference is 32, 10^(32/400) = 10^0.08 = 1.202264434617413.
E_32_LOWER = 0.4540780772195163  # 1 / (1 + 1.202264434617413)
WIN_32_LOWER = 17.469501528975478  # 32 x (1 - 0.4540780772195163)


def close(found: float, wanted: float) -> bool:
    return abs(found - wanted) < 1e-9


def work() -> None:
    while outbox.work():
        pass


def rating_of(name: str, discipline="singles") -> float:
    return Rating.objects.get(user=person(name), discipline=discipline).rating


def ledger(discipline="singles") -> list[tuple]:
    events = RatingEvent.objects.filter(discipline=discipline).order_by(
        "accepted_at", "subject_id", "user_id"
    )
    return [(e.subject_id, e.user_id, e.won, e.before, e.after, e.delta, e.expected) for e in events]


def names(entry: Entry) -> list[str]:
    return [place.user.display_name for place in entry.players.select_related("user")]


# --- the arithmetic ---------------------------------------------------------------------------


def test_equal_singles_ratings_move_sixteen_points():
    delta_a, delta_b, expected_a, expected_b = elo.deltas([1000.0], [1000.0], a_won=True)
    assert (expected_a, expected_b) == (0.5, 0.5)
    assert (1000 + delta_a, 1000 + delta_b) == (1016.0, 984.0)


def test_unequal_ratings_follow_the_hand_worked_fixture():
    assert close(elo.expected(1100.0, 1000.0), E_HIGHER) and close(elo.expected(1000.0, 1100.0), E_LOWER)
    favourite, outsider, _, _ = elo.deltas([1100.0], [1000.0], a_won=True)
    assert close(favourite, WIN_AS_HIGHER) and close(outsider, -WIN_AS_HIGHER)
    favourite, outsider, _, _ = elo.deltas([1100.0], [1000.0], a_won=False)
    assert close(outsider, WIN_AS_LOWER) and close(favourite, -WIN_AS_LOWER)
    # What one side gains the other loses: the two expected scores add up to 1.
    assert close(elo.expected(984.0, 1016.0), E_32_LOWER)


def test_doubles_compares_the_pair_averages_and_gives_each_partner_the_sides_delta():
    # 1200 + 800 and 1050 + 950 both average 1000: an even match, whatever the partners are rated.
    delta_a, delta_b, expected_a, _ = elo.deltas([1200.0, 800.0], [1050.0, 950.0], a_won=True)
    assert expected_a == 0.5 and (delta_a, delta_b) == (16.0, -16.0)
    # Averages 1100 v 1000: the same numbers as the singles fixture.
    delta_a, delta_b, _, _ = elo.deltas([1150.0, 1050.0], [1000.0, 1000.0], a_won=False)
    assert close(delta_a, -WIN_AS_LOWER) and close(delta_b, WIN_AS_LOWER)


# --- what is rated ----------------------------------------------------------------------------


def test_a_played_singles_result_reaches_the_ledger_through_the_worker(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    # Nothing is rated inside the request: the result is official, its rating still processing.
    assert not RatingEvent.objects.exists()
    assert service.pending("singles") is True
    work()
    winner, loser = names(semi.entry_a)[0], names(semi.entry_b)[0]
    assert (rating_of(winner), rating_of(loser)) == (1016.0, 984.0)
    assert service.pending("singles") is False
    event = RatingEvent.objects.get(user=person(winner))
    assert (event.before, event.after, event.delta, event.expected, event.won) == (
        1000.0,
        1016.0,
        16.0,
        0.5,
        True,
    )
    assert not Rating.objects.filter(discipline="doubles").exists()


def test_walkovers_and_retirements_change_no_rating(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, outcome="walkover")
    enter(staff, game, second, second.entry_a, outcome="retired", games=[[11, 5], [3, 2]])
    work()
    assert not RatingEvent.objects.exists() and not Rating.objects.exists()
    assert OfficialResult.objects.filter(projected_at__isnull=False).count() == 2


def test_a_doubles_match_moves_each_partner_in_the_doubles_ledger_only(staff, club, hall):  # noqa: F811
    pairs = [["Amina", "Brian"], ["Chege", "Daudi"]]
    game = started(staff, club, hall, pairs, kind="doubles")
    match = Match.objects.get(draw__event_id=game["event"]["id"])
    enter(staff, game, match, match.entry_a, games=GAMES)
    work()
    for name in names(match.entry_a):
        assert rating_of(name, "doubles") == 1016.0
    for name in names(match.entry_b):
        assert rating_of(name, "doubles") == 984.0
    assert not Rating.objects.filter(discipline="singles").exists()


def test_the_rubbers_of_a_tie_are_rated_and_the_tie_itself_is_not(staff, tie):  # noqa: F811
    rubbers = begin(staff, tie)
    with transaction.atomic():
        for rubber in rubbers[:3]:  # singles, singles, doubles: Tudor wins the tie 3-0
            decide(rubber, tie, "tudor")
    work()
    assert fresh(tie["match"]).status == "completed"
    assert RatingEvent.objects.filter(discipline="singles").count() == 4  # two singles rubbers
    assert RatingEvent.objects.filter(discipline="doubles").count() == 4  # one doubles rubber
    assert not RatingEvent.objects.filter(rubber__isnull=True).exists()  # nothing for the tie as a whole
    # The two rubbers that were not played have no result and no rating.
    assert RatingEvent.objects.values("subject_id").distinct().count() == 3
    first = tie["tudor_players"][0]  # plays the first singles and the doubles
    assert Rating.objects.get(user=first, discipline="singles").rating == 1016.0
    assert Rating.objects.get(user=first, discipline="doubles").rating == 1016.0


# --- order, replay and corrections -------------------------------------------------------------


def test_projecting_the_same_result_again_changes_nothing(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    work()
    before = ledger()
    with transaction.atomic():
        service.project(OfficialResult.objects.get(match=semi))
        service.project(OfficialResult.objects.get(match=semi))
    assert ledger() == before and len(before) == 2


def test_a_corrected_earlier_result_replays_what_came_after_in_the_same_order(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    final = fresh(game["final"])
    enter(staff, game, final, final.entry_a, games=GAMES)
    work()
    order = [subject for subject, *_ in ledger()]
    assert order == [first.id, first.id, second.id, second.id, final.id, final.id]
    champion = names(final.entry_a)[0]
    assert rating_of(champion) == 1032.0  # 1016 v 1016 is even again: another 16

    # The second semi-final is corrected: only the games change, so the final keeps its players.
    unchanged = ledger()
    correct(staff, game, second, second.entry_a, games=[[11, 5], [11, 7], [12, 10]])
    work()
    assert ledger() == unchanged and service.pending("singles") is False

    # The first semi-final's winner is corrected after the final was played; the final is kept.
    correct(staff, game, first, first.entry_b, games=LOST)
    waiting = staff.get(url(game["cup"]) + "corrections/").json()[0]
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    assert staff.post(path, {"choice": "keep", "note": "Final stands"}, format="json").status_code == 200
    work()
    replayed = ledger()
    # The order is the original one: the corrected match keeps its place, ahead of the final.
    assert [subject for subject, *_ in replayed] == order
    loser_now, winner_now = names(first.entry_a)[0], names(first.entry_b)[0]
    by_player = {(subject, user): after for subject, user, _won, _before, after, *_ in replayed}
    assert by_player[(first.id, person(winner_now).id)] == 1016.0
    assert by_player[(first.id, person(loser_now).id)] == 984.0
    # The final was played by the entry that is now the semi-final's loser: it starts from 984 there.
    finalist = person(loser_now).id
    in_final = next(row for row in replayed if (row[0], row[1]) == (final.id, finalist))
    assert in_final[3] == 984.0
    # 984 v 1016 through the service, against the hand-worked numbers for a difference of 32.
    finalist_won = in_final[2]
    assert close(in_final[6], E_32_LOWER)
    assert close(in_final[5], WIN_32_LOWER if finalist_won else WIN_32_LOWER - 32.0)

    # A clean rebuild from nothing gives the same ledger, to 1e-9.
    with transaction.atomic():
        service.rebuild("singles")
    clean = ledger()
    assert len(clean) == len(replayed)
    for left, right in zip(replayed, clean, strict=True):
        assert left[:3] == right[:3]
        assert all(close(a, b) for a, b in zip(left[3:], right[3:], strict=True))
    assert Rating.objects.filter(discipline="singles").count() == 4


def test_a_result_struck_out_to_be_replayed_leaves_the_ledger(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    final = fresh(game["final"])
    enter(staff, game, final, final.entry_a, games=GAMES)
    work()
    assert RatingEvent.objects.count() == 6
    correct(staff, game, first, first.entry_b, games=LOST)
    waiting = staff.get(url(game["cup"]) + "corrections/").json()[0]
    path = url(game["cup"]) + f"corrections/{waiting['id']}/resolve/"
    assert staff.post(path, {"choice": "replace", "note": "Replay"}, format="json").status_code == 200
    work()
    assert not RatingEvent.objects.filter(match=final).exists()
    assert RatingEvent.objects.count() == 4
    assert set(Rating.objects.values_list("played", flat=True)) == {1}
    assert service.pending() is False


def test_a_result_corrected_to_a_walkover_takes_its_ratings_away(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    enter(staff, game, semi, semi.entry_a, games=GAMES)
    work()
    assert Rating.objects.count() == 2
    correct(staff, game, semi, semi.entry_a, outcome="walkover", games=[], reason="Never played")
    work()
    assert not RatingEvent.objects.exists() and not Rating.objects.exists()


# --- what players see --------------------------------------------------------------------------


def test_the_ranking_names_its_discipline_and_scope_and_shows_form(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    viewer = logged_in(make_user("viewer@example.com", display_name="Viewer"))
    shown = viewer.get("/api/v1/rankings/").json()
    assert (shown["discipline"], shown["scope"], shown["processing"], shown["rows"]) == (
        "singles",
        "platform",
        True,
        [],
    )
    work()
    shown = viewer.get("/api/v1/rankings/?discipline=singles").json()
    assert shown["processing"] is False and shown["count"] == 4
    assert [row["rank"] for row in shown["rows"]] == [1, 1, 3, 3]  # level ratings share a rank
    top = shown["rows"][0]
    assert (top["rating"], top["played"], top["won"], top["form"], top["last_delta"]) == (
        1016.0,
        1,
        1,
        ["W"],
        16.0,
    )
    assert top["is_me"] is False and top["listed"] is False
    assert viewer.get("/api/v1/rankings/?discipline=doubles").json()["rows"] == []
    assert viewer.get("/api/v1/rankings/?discipline=mixed").status_code == 400
    assert viewer.get("/api/v1/rankings/?organization=nonsense").status_code == 400
    # A club's ranking is for its members.
    refused = viewer.get(f"/api/v1/rankings/?organization={club.id}")
    assert refused.status_code == 403
    mine = staff.get(f"/api/v1/rankings/?organization={club.id}").json()
    assert (mine["scope"], mine["organization_name"]) == ("club", club.name)


def test_club_rankings_sum_current_ratings_of_active_members_by_discipline():
    coast = Organization.objects.create(name="Coast", town="Mombasa")
    nyali = Organization.objects.create(name="Nyali", town="Mombasa", kind=Organization.Kind.CLUB_FACILITY)
    tudor = Organization.objects.create(name="Tudor", town="Mombasa")
    facility = Organization.objects.create(name="Tables", town="Mombasa", kind=Organization.Kind.FACILITY)
    shared = make_user("shared@example.com")
    singles = make_user("singles@example.com")
    left = make_user("left@example.com")
    inactive = make_user("inactive@example.com")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    unrated = make_user("unrated@example.com")
    Membership.objects.bulk_create(
        [
            Membership(organization=coast, user=shared),
            Membership(organization=coast, user=singles),
            Membership(organization=coast, user=left, status=Membership.Status.LEFT),
            Membership(organization=coast, user=inactive),
            Membership(organization=coast, user=unrated),
            Membership(organization=nyali, user=shared),
            Membership(organization=tudor, user=shared),
            Membership(organization=facility, user=shared),
        ]
    )
    Rating.objects.bulk_create(
        [
            Rating(user=shared, discipline="singles", rating=1016.25, played=2),
            Rating(user=shared, discipline="doubles", rating=984, played=1),
            Rating(user=singles, discipline="singles", rating=950, played=1),
            Rating(user=left, discipline="singles", rating=1500, played=2),
            Rating(user=inactive, discipline="singles", rating=1500, played=2),
            Rating(user=unrated, discipline="singles"),
        ]
    )
    viewer = logged_in(make_user("club-rankings-viewer@example.com"))
    endpoint = "/api/v1/rankings/clubs/"
    shown = viewer.get(endpoint).json()
    assert shown["discipline"] == "singles" and shown["processing"] is False
    assert [
        (row["name"], row["rank"], row["total_points"], row["rated_members"]) for row in shown["rows"]
    ] == [
        ("Coast", 1, 1966.25, 2),
        ("Nyali", 2, 1016.25, 1),
        ("Tudor", 2, 1016.25, 1),
    ]
    assert set(shown["rows"][0]) == {
        "organization_id",
        "town",
        "name",
        "rank",
        "total_points",
        "rated_members",
    }
    doubles = viewer.get(endpoint + "?discipline=doubles").json()
    assert doubles["discipline"] == "doubles"
    assert [(row["name"], row["rank"], row["total_points"]) for row in doubles["rows"]] == [
        ("Coast", 1, 984),
        ("Nyali", 1, 984),
        ("Tudor", 1, 984),
    ]
    assert viewer.get(endpoint + "?discipline=mixed").status_code == 400


def test_geography_groups_players_by_their_full_location_and_discipline():
    locations = [
        ("KE", "Coast", "Springfield", 1200),
        ("KE", "coast", "springfield", 900),
        ("KE", "Central", "Springfield", 1100),
        ("TZ", "Coast", "Springfield", 1800),
        ("", "", "", 2000),
    ]
    for index, (country, region, city, rating) in enumerate(locations):
        player = make_user(f"geo-{index}@example.com")
        PlayerProfile.objects.create(user=player, country=country, region=region, city=city)
        Rating.objects.create(user=player, discipline="singles", rating=rating, played=1)
    viewer = logged_in(make_user("geography-viewer@example.com"))
    endpoint = "/api/v1/rankings/geography/"
    countries = viewer.get(endpoint).json()["rows"]
    assert [(row["country"], row["total_points"], row["rated_players"]) for row in countries] == [
        ("KE", 3200, 3),
        ("TZ", 1800, 1),
    ]
    cities = viewer.get(endpoint + "?level=city").json()["rows"]
    assert [
        (row["country"], row["region"].lower(), row["city"].lower(), row["total_points"]) for row in cities
    ] == [
        ("KE", "coast", "springfield", 2100),
        ("TZ", "coast", "springfield", 1800),
        ("KE", "central", "springfield", 1100),
    ]
    assert viewer.get(endpoint + "?discipline=doubles&level=region").json()["rows"] == []
    assert viewer.get(endpoint + "?level=unknown").status_code == 400


def test_a_players_history_shows_before_and_after_and_can_be_filtered(staff, club, hall):  # noqa: F811
    game = knockout(staff, club, hall)
    first, second = game["semis"]
    enter(staff, game, first, first.entry_a, games=GAMES)
    enter(staff, game, second, second.entry_a, games=GAMES)
    final = fresh(game["final"])
    enter(staff, game, final, final.entry_a, games=GAMES)
    work()
    runner_up = person(names(final.entry_b)[0])
    viewer = logged_in(make_user("viewer@example.com", display_name="Viewer"))
    shown = viewer.get(f"/api/v1/players/{runner_up.id}/ratings/").json()
    singles, doubles = shown["summaries"]
    assert (singles["discipline"], singles["played"], singles["won"], singles["form"]) == (
        "singles",
        2,
        1,
        ["L", "W"],
    )
    assert (singles["rank"], singles["ranked"]) == (2, 4)
    assert (doubles["rating"], doubles["played"], doubles["rank"]) == (None, 0, None)
    assert shown["history"][0]["corrected"] is False and shown["history"][0]["timezone"]
    assert shown["count"] == 2 and [change["won"] for change in shown["history"]] == [False, True]
    lost = shown["history"][0]
    assert (lost["before"], lost["after"], lost["delta"]) == (1016.0, 1000.0, -16.0)
    assert lost["opponents"] == names(final.entry_a) and lost["partner"] == ""
    assert lost["games"] == LOST and lost["tournament_name"] == "Coast Open"
    won = viewer.get(f"/api/v1/players/{runner_up.id}/ratings/?result=won").json()
    assert won["count"] == 1 and won["history"][0]["after"] == 1016.0
    assert viewer.get(f"/api/v1/players/{runner_up.id}/ratings/?result=drawn").status_code == 400
    # Somebody with no rated match and no page in the directory is not found; their own is.
    stranger = make_user("stranger@example.com", display_name="Stranger")
    assert viewer.get(f"/api/v1/players/{stranger.id}/ratings/").status_code == 404
    assert logged_in(stranger).get(f"/api/v1/players/{stranger.id}/ratings/").json()["count"] == 0
