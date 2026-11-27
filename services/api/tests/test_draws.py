"""Draw generation, versions and publication (REQ-009, EVAL-009, TASK-019).

The expectations in the fixture tests are worked out by hand from ITTF Statutes 2026, 3.6.1, 3.6.2 and
3.7.5 (transcribed in spec.md, fixtures listed in test.md), never from the code under test.
"""

import random
import uuid
from itertools import combinations

import pytest
from django.core.cache import cache

from competitions import drawing, draws
from competitions.models import DrawVersion, Entry, Event, Match

from .helpers import logged_in
from .test_entries import act, enter, player
from .test_tournaments import add_event, do, make_tournament, url
from .test_venues import make_venue

pytestmark = pytest.mark.django_db


def ids(count: int) -> list[str]:
    return [f"e{number:02d}" for number in range(1, count + 1)]


def knockout(plan):
    return [m for m in plan.matches if m.stage == "knockout"]


def pair(match) -> tuple:
    return (match.a.entry, match.b.entry if match.b else None)


# --- Fixtures F-KO: knockout (3.6.1, 3.6.2) ------------------------------------------------------


@pytest.mark.parametrize("rng_seed", range(25))
def test_fko8_eight_entries_four_seeds(rng_seed):
    entries = ids(8)
    s1, s2, s3, s4 = seeds = ["e03", "e07", "e01", "e05"]
    plan = draws.build("knockout", entries, seeds, rng_seed)

    assert plan.lines[0] == s1 and plan.lines[7] == s2  # top of the first half, bottom of the second
    assert {plan.lines[3], plan.lines[4]} == {s3, s4}  # bottom of the first half, top of the second
    assert sorted(plan.lines) == entries  # everybody once, no byes
    rounds = [[m for m in knockout(plan) if m.round == r] for r in (1, 2, 3)]
    assert [len(r) for r in rounds] == [4, 2, 1]
    assert all(m.b is not None and m.a.entry != m.b.entry for m in rounds[0])
    # Later rounds wait for the winners of the two matches above them.
    assert [(m.a.feeder, m.b.feeder) for m in rounds[1]] == [((1, 1), (1, 2)), ((1, 3), (1, 4))]
    assert (rounds[2][0].a.feeder, rounds[2][0].b.feeder) == ((2, 1), (2, 2))
    assert plan.seeds == {s1: 1, s2: 2, s3: 3, s4: 4}


def test_seeds_three_and_four_are_drawn_not_fixed():
    seeds = ["e03", "e07", "e01", "e05"]
    seen = {draws.build("knockout", ids(8), seeds, n).lines[3] for n in range(40)}
    assert seen == {"e01", "e05"}


@pytest.mark.parametrize("rng_seed", range(25))
def test_fko6_six_entries_two_seeds_have_two_byes_against_the_seeds(rng_seed):
    plan = draws.build("knockout", ids(6), ["e02", "e06"], rng_seed)

    assert plan.lines[0] == "e02" and plan.lines[1] is None  # seed 1 has the first bye
    assert plan.lines[7] == "e06" and plan.lines[6] is None  # seed 2 the second
    assert sorted(plan.lines[2:6]) == ["e01", "e03", "e04", "e05"]
    first = [m for m in knockout(plan) if m.round == 1]
    assert [m.b is None for m in first] == [True, False, False, True]
    assert pair(first[0]) == ("e02", None) and pair(first[3]) == ("e06", None)
    # A bye is not a match against oneself and the seed is already in the semi-final.
    semis = [m for m in knockout(plan) if m.round == 2]
    assert semis[0].a.entry == "e02" and semis[0].b.feeder == (1, 2)
    assert semis[1].a.feeder == (1, 3) and semis[1].b.entry == "e06"
    assert len(knockout(plan)) == 7


@pytest.mark.parametrize(
    ("count", "byes"),
    [(2, 0), (3, 1), (5, 3), (9, 7), (10, 6), (12, 4), (16, 0), (17, 15), (20, 12), (33, 31)],
)
def test_byes_fill_the_first_round_to_a_power_of_two_and_are_spread_evenly(count, byes):
    for rng_seed in range(10):
        lines = draws.build("knockout", ids(count), [], rng_seed).lines
        size = len(lines)
        assert size & (size - 1) == 0 and size >= count > size // 2
        assert lines.count(None) == byes
        assert sorted(line for line in lines if line) == ids(count)
        # Never two byes in one match, and the halves differ by one bye at most.
        assert all(lines[i] or lines[i + 1] for i in range(0, size, 2))
        top, bottom = lines[: size // 2].count(None), lines[size // 2 :].count(None)
        assert abs(top - bottom) <= 1
        for parts in (4, 8, 16):  # quarters, eighths, sixteenths: one bye apart at most
            if size >= parts * 2:
                width = size // parts
                counts = [lines[i : i + width].count(None) for i in range(0, size, width)]
                assert max(counts) - min(counts) <= 1


@pytest.mark.parametrize("count", range(2, 66))
def test_byes_are_even_for_every_field_size_and_any_number_of_seeds(count):
    size = draws.bracket_size(count)
    for seeds in {min(wanted, size // 2) for wanted in (0, 1, 2, 4, 8)}:
        for rng_seed in range(8):
            lines = draws.build("knockout", ids(count), ids(count)[:seeds], rng_seed).lines
            assert lines.count(None) == size - count
            assert all(lines[i] or lines[i + 1] for i in range(0, size, 2))
            assert abs(lines[: size // 2].count(None) - lines[size // 2 :].count(None)) <= 1
            # Seeds get the byes first, in seeding order.
            at = {entry: line for line, entry in enumerate(lines, start=1)}
            with_bye = [lines[draws.opponent(at[seed]) - 1] is None for seed in ids(count)[:seeds]]
            assert with_bye == sorted(with_bye, reverse=True)


def test_sixteen_entries_eight_seeds_go_to_the_places_named_for_them():
    seeds = ids(16)[:8]
    for rng_seed in range(20):
        lines = draws.build("knockout", ids(16), seeds, rng_seed).lines
        at = {entry: line for line, entry in enumerate(lines, start=1)}
        assert at["e01"] == 1 and at["e02"] == 16
        assert {at["e03"], at["e04"]} == {8, 9}
        # 5-8: bottom of the odd-numbered quarters (4, 12) and top of the even-numbered ones (5, 13).
        assert {at[s] for s in seeds[4:]} == {4, 5, 12, 13}


def test_a_big_knockout_takes_a_seed_for_every_first_round_match():
    seeds = set(ids(128)[:64])
    lines = draws.build("knockout", ids(128), ids(128)[:64], 5).lines
    for first, second in zip(lines[::2], lines[1::2], strict=True):
        assert (first in seeds) != (second in seeds)  # one seed in every first-round match


@pytest.mark.parametrize("rng_seed", range(10))
def test_a_fully_ranked_knockout_plays_the_first_against_the_last(rng_seed):
    plan = draws.build("knockout", ids(8), ids(8), rng_seed)
    assert list(plan.seeds) == ids(8)
    assert plan.lines[0] == "e01" and plan.lines[7] == "e02"
    pairs = {frozenset(pair) for pair in zip(plan.lines[::2], plan.lines[1::2], strict=True)}
    assert pairs == {frozenset(p) for p in (("e01", "e08"), ("e02", "e07"), ("e03", "e06"), ("e04", "e05"))}


@pytest.mark.parametrize("rng_seed", range(10))
def test_entries_ranked_below_the_seeded_places_meet_the_lowest_seeds_and_byes_stay_with_the_best(rng_seed):
    # 37 entries in a bracket of 64: 27 byes for seeds 1-27, and seeds 33-37 against 32, 31, 30, 29, 28.
    lines = draws.build("knockout", ids(37), ids(37), rng_seed).lines
    against = {}
    for first, second in zip(lines[::2], lines[1::2], strict=True):
        against[first], against[second] = second, first
    assert all(against[seed] is None for seed in ids(27))
    assert [against[seed] for seed in ids(37)[32:]] == ["e32", "e31", "e30", "e29", "e28"]
    assert sorted(entry for entry in lines if entry) == ids(37)
    # Six ranked of six: the two byes go to 1 and 2, then 3 v 6 and 4 v 5.
    lines = draws.build("knockout", ids(6), ids(6), rng_seed).lines
    pairs = {frozenset(pair) for pair in zip(lines[::2], lines[1::2], strict=True)}
    assert pairs == {
        frozenset(("e01", None)),
        frozenset(("e02", None)),
        frozenset(("e03", "e06")),
        frozenset(("e04", "e05")),
    }


def test_every_entry_of_a_group_event_may_be_seeded():
    plan = draws.build("groups_knockout", ids(37), ids(37), 3, group_count=8, qualifiers_per_group=2)
    assert [group[0] for group in plan.groups] == ids(8)  # the top eight head a group each
    assert plan.groups[7][1] == "e09" and plan.groups[0][1] == "e16"  # then the snake turns back
    assert sorted(len(group) for group in plan.groups) == [4, 4, 4, 5, 5, 5, 5, 5]
    assert draws.build("round_robin", ids(40), ids(40), 3).groups == [ids(40)]


def test_unknown_or_repeated_seeds_and_a_single_entry_are_refused():
    with pytest.raises(draws.DrawError):
        draws.build("knockout", ids(6), ["nobody"], 1)
    with pytest.raises(draws.DrawError):
        draws.build("knockout", ids(6), ["e01", "e01"], 1)
    with pytest.raises(draws.DrawError):
        draws.build("knockout", ids(1), [], 1)


# --- Fixtures F-RR: round robin (3.7.5.1, 3.7.5.5) ----------------------------------------------


@pytest.mark.parametrize(("count", "rounds"), [(2, 1), (3, 3), (4, 3), (5, 5), (6, 5), (7, 7)])
def test_frr_every_pair_meets_once_and_nobody_plays_twice_in_a_round(count, rounds):
    schedule = draws.round_robin(count)
    assert len(schedule) == rounds
    played = [match for round_ in schedule for match in round_]
    assert sorted(played) == list(combinations(range(1, count + 1), 2))
    for round_ in schedule:
        numbers = [n for match in round_ for n in match]
        assert len(numbers) == len(set(numbers))
    assert (1, 2) in schedule[-1]  # one qualifies: 1 v 2 is the last match (3.7.5.5)


def test_frr_the_deciding_match_follows_the_number_of_qualifiers():
    assert (2, 3) in draws.round_robin(4, qualifiers=2)[-1]
    assert (3, 4) in draws.round_robin(5, qualifiers=3)[-1]


def test_frr4_a_round_robin_event_is_one_group_numbered_by_seed():
    plan = draws.build("round_robin", ids(4), ["e04", "e02"], 7)
    assert plan.groups[0][:2] == ["e04", "e02"] and sorted(plan.groups[0]) == ids(4)
    assert len(plan.matches) == 6 and {m.stage for m in plan.matches} == {"group"}
    last = [pair(m) for m in plan.matches if m.round == 3]
    assert ("e04", "e02") in last
    assert plan.lines == []


# --- Fixtures F-GK: groups, then knockout ---------------------------------------------------------


@pytest.mark.parametrize("rng_seed", range(25))
def test_fgk8_two_groups_two_through(rng_seed):
    seeds = ["e05", "e01", "e08", "e03"]
    plan = draws.build("groups_knockout", ids(8), seeds, rng_seed, group_count=2, qualifiers_per_group=2)

    a, b = plan.groups
    assert a[:2] == ["e05", "e03"] and b[:2] == ["e01", "e08"]  # snake: 1 and 4, 2 and 3
    assert len(a) == len(b) == 4 and sorted(a + b) == ids(8)
    group_matches = [m for m in plan.matches if m.stage == "group"]
    assert len(group_matches) == 12
    for number, members in ((1, a), (2, b)):
        mine = [m for m in group_matches if m.group == number]
        assert sorted(tuple(sorted(pair(m))) for m in mine) == sorted(combinations(sorted(members), 2))
        assert (members[1], members[2]) in [pair(m) for m in mine if m.round == 3]  # 2 v 3 last

    # Four qualifiers, no byes: winners at the top and the bottom, each runner-up in the other half.
    semis = [m for m in knockout(plan) if m.round == 1]
    assert [(m.a.qualifier, m.b.qualifier) for m in semis] == [((1, 1), (2, 2)), ((1, 2), (2, 1))]
    final = [m for m in knockout(plan) if m.round == 2]
    assert [(m.a.feeder, m.b.feeder) for m in final] == [((1, 1), (1, 2))]
    assert all(m.a.entry is None for m in knockout(plan))  # nobody is through before the groups are played


@pytest.mark.parametrize("rng_seed", range(25))
def test_fgk6_three_groups_one_through_gives_the_first_winner_the_bye(rng_seed):
    plan = draws.build("groups_knockout", ids(6), [], rng_seed, group_count=3, qualifiers_per_group=1)
    assert [len(g) for g in plan.groups] == [2, 2, 2]
    first = [m for m in knockout(plan) if m.round == 1]
    assert (first[0].a.qualifier, first[0].b) == ((1, 1), None)
    assert (first[1].a.qualifier, first[1].b.qualifier) == ((3, 1), (2, 1))
    final = next(m for m in knockout(plan) if m.round == 2)
    # The bye is known only once group A is decided, so the final waits for both matches.
    assert (final.a.feeder, final.b.feeder) == ((1, 1), (1, 2))


def test_fgk_groups_differ_by_one_at_most_and_runners_up_avoid_their_winner():
    for count in range(8, 30):
        for groups in (2, 3, 4, 5):
            if count < groups * 3:
                continue
            plan = draws.build(
                "groups_knockout",
                ids(count),
                ids(count)[:groups],
                3,
                group_count=groups,
                qualifiers_per_group=2,
            )
            sizes = [len(g) for g in plan.groups]
            assert max(sizes) - min(sizes) <= 1 and sum(sizes) == count
            assert [g[0] for g in plan.groups] == ids(count)[:groups]  # seed n heads group n
            first = [m for m in knockout(plan) if m.round == 1]
            lines = [side.qualifier if side else None for m in first for side in (m.a, m.b)]
            half = {q: index >= len(lines) // 2 for index, q in enumerate(lines) if q}
            assert len(half) == groups * 2
            if groups == 2:
                assert all(half[g, 1] != half[g, 2] for g in (1, 2))
            assert lines.count(None) == len(lines) - groups * 2
            assert all(m.a is not None for m in first)


def test_too_few_entries_for_the_groups_is_refused():
    with pytest.raises(draws.DrawError, match="at least 6"):
        draws.build("groups_knockout", ids(5), [], 1, group_count=2, qualifiers_per_group=2)


# --- Reproducibility ---------------------------------------------------------------------------


def test_the_same_entries_seeds_and_number_always_give_the_same_draw():
    entries = ids(13)
    shuffled = random.Random(5).sample(entries, len(entries))
    for fmt, extra in (
        ("knockout", {}),
        ("round_robin", {}),
        ("groups_knockout", {"group_count": 3, "qualifiers_per_group": 2}),
    ):
        one = draws.build(fmt, entries, ["e09", "e02"], 2026, **extra)
        two = draws.build(fmt, shuffled, ["e09", "e02"], 2026, **extra)
        assert one == two
    assert draws.build("knockout", entries, [], 1).lines != draws.build("knockout", entries, [], 2).lines


# --- Kept draws: preview, publication, versions (API) ---------------------------------------------


def draw_url(tournament, event, action=""):
    return url(tournament, event=event) + "draw/" + (f"{action}/" if action else "")


@pytest.fixture
def cup(staff, club):
    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, name="Singles", seeding="manual")
    add_event(
        staff, tournament, name="Groups", format="groups_knockout", group_count=2, qualifiers_per_group=1
    )
    return do(staff, tournament, "publish")


def fill(staff, cup, event, count) -> list[dict]:
    made = []
    for n in range(count):
        if n % 25 == 0:
            cache.clear()  # the entry desk's rate limit is not the subject here
        made.append(enter(staff, cup, event, player_ids=[str(player(f"{event['name']}{n}").id)]))
    return made


def test_staff_preview_and_publish_a_draw_and_everyone_sees_the_published_one(staff, cup):
    singles = cup["events"][0]
    entries = fill(staff, cup, singles, 6)
    viewer = logged_in(player("Viewer"))
    assert viewer.get(draw_url(cup, singles)).json() == {
        "published": None,
        "preview": None,
        "recommended_seeds": [],
    }

    seeds = [entries[4]["id"], entries[1]["id"]]
    made = staff.post(
        draw_url(cup, singles, "preview"), {"seeded_entry_ids": seeds, "rng_seed": 11}, format="json"
    )
    assert made.status_code == 200, made.json()
    preview = made.json()["preview"]
    assert made.json()["published"] is None
    assert (preview["version"], preview["status"], preview["rules_version"]) == (
        1,
        "preview",
        "ITTF-2026-ch3",
    )
    assert preview["rng_seed"] == 11 and preview["stale"] is False and preview["groups"] == []
    by_line = {place["bracket_position"]: place for place in preview["places"]}
    assert by_line[1]["entry"]["id"] == seeds[0] and by_line[1]["seed"] == 1
    assert by_line[8]["entry"]["id"] == seeds[1] and by_line[8]["seed"] == 2
    assert sorted(by_line) == [1, 3, 4, 5, 6, 8]  # lines 2 and 7 are the byes
    assert (
        by_line[1]["entry"]["title"] == "Singles4"
        and by_line[1]["entry"]["players"][0]["display_name"] == "Singles4"
    )

    matches = preview["matches"]
    assert [(m["round"], m["round_name"]) for m in matches] == [(1, "Quarter-final")] * 4 + [
        (2, "Semi-final")
    ] * 2 + [(3, "Final")]
    bye = matches[0]
    assert bye["b"] is None and bye["status"] == "bye" and bye["winner_id"] == seeds[0]
    assert bye["a"]["entry"]["id"] == seeds[0] and bye["a"]["seed"] == 1
    semi = matches[4]
    assert semi["a"]["entry"]["id"] == seeds[0]
    assert semi["b"] == {"entry": None, "seed": None, "awaiting": "Winner of quarter-final 2"}
    assert matches[6]["a"]["awaiting"] == "Winner of semi-final 1"

    # A preview is the organizers' own: nobody else sees it, and drawing again replaces it.
    assert viewer.get(draw_url(cup, singles)).json() == {
        "published": None,
        "preview": None,
        "recommended_seeds": [],
    }
    again = staff.post(
        draw_url(cup, singles, "preview"), {"seeded_entry_ids": seeds, "rng_seed": 11}, format="json"
    ).json()
    assert again["preview"]["version"] == 1  # a replaced preview gives its number back
    assert [p["entry"]["id"] for p in again["preview"]["places"]] == [
        p["entry"]["id"] for p in preview["places"]
    ]
    assert DrawVersion.objects.count() == 1

    published = staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()
    assert published["preview"] is None and published["published"]["status"] == "published"
    seen = viewer.get(draw_url(cup, singles)).json()
    assert seen["preview"] is None and seen["published"] == published["published"]
    assert set(seen["published"]) == {
        "id", "version", "status", "rules_version", "rng_seed", "stale", "created_at", "published_at",
        "moved_at", "keep_apart", "same_group_limit", "over_limit", "groups", "places", "matches",
    }  # fmt: skip
    # Who is kept apart from whom is for the organizers' preview only.
    assert seen["published"]["over_limit"] == [] and all(
        not p["affiliations"] for p in seen["published"]["places"]
    )
    # Reloading gives the same draw: a published version doesn't move.
    assert viewer.get(draw_url(cup, singles)).json() == seen
    assert staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["code"] == "no_preview"


def test_a_new_version_supersedes_the_published_draw_and_a_changed_field_makes_it_stale(staff, cup):
    singles = cup["events"][0]
    entries = fill(staff, cup, singles, 4)
    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    first = staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["published"]
    assert first["version"] == 1

    # Somebody withdraws: the published draw no longer matches the entries and says so.
    act(staff, cup, singles, entries[0], "staff-withdraw")
    shown = staff.get(draw_url(cup, singles)).json()["published"]
    assert shown["stale"] is True and shown["id"] == first["id"]

    # A preview drawn before another change can't be published; a fresh one can.
    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    enter(staff, cup, singles, player_ids=[str(player("Late").id)])
    refused = staff.post(draw_url(cup, singles, "publish"), {}, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "draw_stale"
    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    second = staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["published"]
    assert second["version"] == 2 and second["stale"] is False
    assert list(DrawVersion.objects.order_by("version").values_list("version", "status")) == [
        (1, "superseded"),
        (2, "published"),
    ]
    assert len(second["places"]) == 4


def test_groups_then_knockout_is_kept_with_its_placeholders(staff, cup):
    groups = cup["events"][1]
    fill(staff, cup, groups, 7)
    draw = staff.post(draw_url(cup, groups, "preview"), {"rng_seed": 3}, format="json").json()["preview"]
    assert draw["groups"] == [{"number": 1, "name": "Group A"}, {"number": 2, "name": "Group B"}]
    sizes = [len([p for p in draw["places"] if p["group"] == n]) for n in (1, 2)]
    assert sorted(sizes) == [3, 4]
    assert all(p["bracket_position"] is None and p["group_position"] for p in draw["places"])
    group_matches = [m for m in draw["matches"] if m["stage"] == "group"]
    assert len(group_matches) == 3 + 6 and {m["round_name"] for m in group_matches} == {
        "Round 1",
        "Round 2",
        "Round 3",
    }
    final = [m for m in draw["matches"] if m["stage"] == "knockout"]
    assert len(final) == 1 and final[0]["round_name"] == "Final"
    assert (final[0]["a"]["awaiting"], final[0]["b"]["awaiting"]) == ("Group A winner", "Group B winner")

    # A qualifier with a bye is named in the next round, not as the "winner" of a match nobody plays.
    staff.patch(url(cup, event=groups), {"group_count": 3}, format="json")
    three = staff.post(draw_url(cup, groups, "preview"), {"rng_seed": 3}, format="json").json()["preview"]
    last = [m for m in three["matches"] if m["stage"] == "knockout"][-1]
    assert (last["a"]["awaiting"], last["b"]["awaiting"]) == ("Group A winner", "Winner of semi-final 2")


def test_winners_move_on_and_a_bye_is_never_a_played_match(staff, cup):
    singles = cup["events"][0]
    entries = fill(staff, cup, singles, 3)
    staff.post(draw_url(cup, singles, "preview"), {"seeded_entry_ids": [entries[0]["id"]]}, format="json")
    staff.post(draw_url(cup, singles, "publish"), {}, format="json")
    bye, semi, final = Match.objects.order_by("round", "position")
    seed = Entry.objects.get(pk=entries[0]["id"])

    assert (bye.status, bye.entry_a, bye.entry_b, bye.winner) == ("bye", seed, None, seed)
    assert final.entry_a == seed and final.entry_b is None and final.feeder_b == semi
    with pytest.raises(Exception, match="already decided"):
        drawing.record_result(bye, seed)
    with pytest.raises(Exception, match="aren't known yet"):
        drawing.record_result(final, seed)
    with pytest.raises(Exception, match="one of the two sides"):
        drawing.record_result(semi, seed)

    drawing.record_result(semi, semi.entry_b, games=[(5, 11)] * 3)
    final.refresh_from_db()
    assert final.entry_b == semi.entry_b and final.status == "scheduled"
    with pytest.raises(Exception, match="don't fit"):
        drawing.record_result(final, seed)  # a played match has its games
    drawing.record_result(final, seed, games=[(11, 5)] * 3)
    final.refresh_from_db()
    assert final.winner == seed and final.status == "completed"
    with pytest.raises(Exception, match="already decided"):
        drawing.record_result(final, seed)


def test_every_entry_may_be_seeded_whatever_the_format(staff, cup):
    """A national field is bigger than 32: the organizers rank all 34 entries of each event."""
    for event in cup["events"]:
        ranked = [entry["id"] for entry in fill(staff, cup, event, 34)]
        made = staff.post(draw_url(cup, event, "preview"), {"seeded_entry_ids": ranked}, format="json")
        assert made.status_code == 200, made.json()
        seeded = sorted((p["seed"], p["entry"]["id"]) for p in made.json()["preview"]["places"])
        assert [entry_id for _, entry_id in seeded] == ranked

    endless = [ranked[0]] * (draws.MAX_SEEDS + 1)  # a bound on the request, far above any field
    refused = staff.post(draw_url(cup, event, "preview"), {"seeded_entry_ids": endless}, format="json")
    assert refused.status_code == 400 and "seeded_entry_ids" in refused.json()["fields"]


def test_staff_delete_a_preview_to_draw_again_and_the_published_draw_stays(staff, cup):
    singles = cup["events"][0]
    fill(staff, cup, singles, 4)
    stranger = logged_in(player("Passerby"))
    assert stranger.post(draw_url(cup, singles, "discard"), {}, format="json").status_code == 403

    staff.post(draw_url(cup, singles, "preview"), {"rng_seed": 1}, format="json")
    cleared = staff.post(draw_url(cup, singles, "discard"), {}, format="json")
    assert cleared.status_code == 200 and cleared.json()["preview"] is None
    assert not DrawVersion.objects.exists() and not Match.objects.exists()
    assert staff.post(draw_url(cup, singles, "discard"), {}, format="json").status_code == 200  # nothing left
    assert staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["code"] == "no_preview"

    staff.post(draw_url(cup, singles, "preview"), {"rng_seed": 2}, format="json")
    published = staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["published"]
    staff.post(draw_url(cup, singles, "preview"), {"rng_seed": 3}, format="json")
    after = staff.post(draw_url(cup, singles, "discard"), {}, format="json").json()
    assert after["preview"] is None and after["published"]["id"] == published["id"]
    assert after["published"]["matches"] == published["matches"]

    do(staff, cup, "start")
    do(staff, cup, "start", singles)
    closed = staff.post(draw_url(cup, singles, "discard"), {}, format="json")
    assert closed.status_code == 409 and closed.json()["code"] == "draw_closed"


def test_draws_are_for_staff_before_the_event_starts(staff, club, cup):
    singles, groups = cup["events"]
    entries = fill(staff, cup, singles, 2)
    stranger = logged_in(player("Stranger"))
    for action in ("preview", "publish"):
        assert stranger.post(draw_url(cup, singles, action), {}, format="json").status_code == 403

    def refused(event, code, **body):
        response = staff.post(draw_url(cup, event, "preview"), body, format="json")
        assert response.status_code == 409 and response.json()["code"] == code, response.json()

    refused(groups, "draw_not_possible")  # nobody has entered
    refused(singles, "draw_not_possible", seeded_entry_ids=[entries[0]["id"], str(uuid.uuid4())])
    staff.patch(url(cup, event=singles), {"seeding": "none"}, format="json")
    refused(singles, "unseeded_event", seeded_entry_ids=[entries[0]["id"]])

    draft = add_event(staff, make_tournament(staff, club, name="Next year"))
    response = staff.post(draw_url(draft, draft["events"][0], "preview"), {}, format="json")
    assert response.json()["code"] == "not_published"
    assert stranger.get(draw_url(draft, draft["events"][0])).status_code == 404

    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    staff.post(draw_url(cup, singles, "publish"), {}, format="json")
    do(staff, cup, "start")
    do(staff, cup, "start", singles)
    refused(singles, "draw_closed")
    assert staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["code"] == "draw_closed"
    assert stranger.get(draw_url(cup, singles)).json()["published"]["version"] == 1


def test_a_qualifier_never_meets_their_own_group_in_the_first_knockout_round_when_avoidable():
    for groups in range(2, 17):
        for rng_seed in range(40):
            first = draws.qualifier_lines(groups, 2, random.Random(rng_seed))
            for top, bottom in zip(first[::2], first[1::2], strict=True):
                assert not (top and bottom and top[0] == bottom[0]), (groups, rng_seed)


def test_a_draw_made_for_another_format_is_stale(staff, cup):
    singles = cup["events"][0]
    fill(staff, cup, singles, 4)
    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    staff.post(draw_url(cup, singles, "publish"), {}, format="json")
    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    assert staff.patch(url(cup, event=singles), {"format": "round_robin"}, format="json").status_code == 200
    shown = staff.get(draw_url(cup, singles)).json()
    assert shown["published"]["stale"] is True and shown["preview"]["stale"] is True
    assert staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["code"] == "draw_stale"


def test_rating_seeds_are_recommended_and_the_organizers_may_change_them(staff, club):
    """TASK-098: rated entries are seeded by singles rating, unrated ones are not, and seeds the
    organizers send replace the recommendation."""
    from ratings.models import Discipline, Rating

    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(staff, tournament, name="Open", seeding="rating")
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    entries = fill(staff, tournament, event, 6)
    points = {0: 1450.0, 2: 1610.0, 3: 1380.0, 5: 1520.0}
    for index, rating in points.items():
        user = Entry.objects.get(pk=entries[index]["id"]).players.get().user
        Rating.objects.create(user=user, discipline=Discipline.SINGLES, rating=rating, played=3)
    # Played nothing yet: a rating row at the start value is not a reason to seed.
    newcomer = Entry.objects.get(pk=entries[1]["id"]).players.get().user
    Rating.objects.create(user=newcomer, discipline=Discipline.SINGLES, played=0)

    recommended = [entries[i]["id"] for i in (2, 5, 0, 3)]  # six entries: a bracket of 8 takes 4 seeds
    assert staff.get(draw_url(tournament, event)).json()["recommended_seeds"] == recommended
    viewer = logged_in(player("Onlooker"))
    assert viewer.get(draw_url(tournament, event)).json()["recommended_seeds"] == []

    drawn = staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 3}, format="json").json()
    seeded = sorted((p["seed"], p["entry"]["id"]) for p in drawn["preview"]["places"] if p["seed"])
    assert [entry_id for _, entry_id in seeded] == recommended

    mine = [entries[3]["id"], entries[1]["id"]]
    drawn = staff.post(
        draw_url(tournament, event, "preview"), {"seeded_entry_ids": mine, "rng_seed": 3}, format="json"
    ).json()
    seeded = sorted((p["seed"], p["entry"]["id"]) for p in drawn["preview"]["places"] if p["seed"])
    assert [entry_id for _, entry_id in seeded] == mine
    assert drawing.rating_seeds(Event.objects.get(pk=event["id"])) == recommended
