"""Draw generation, versions and publication (REQ-009, EVAL-009, TASK-019).

The expectations in the fixture tests are worked out by hand from ITTF Statutes 2026, 3.6.1, 3.6.2 and
3.7.5 (transcribed in spec.md, fixtures listed in test.md), never from the code under test.
"""

import random
from itertools import combinations

import pytest

from competitions import drawing, draws
from competitions.models import DrawVersion, Entry, Match

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
    ("count", "byes"), [(2, 0), (3, 1), (5, 3), (9, 7), (12, 4), (16, 0), (17, 15), (33, 31)]
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
        if size >= 8:
            quarters = [lines[i : i + size // 4].count(None) for i in range(0, size, size // 4)]
            assert max(quarters) - min(quarters) <= 1


def test_sixteen_entries_eight_seeds_go_to_the_places_named_for_them():
    seeds = ids(16)[:8]
    for rng_seed in range(20):
        lines = draws.build("knockout", ids(16), seeds, rng_seed).lines
        at = {entry: line for line, entry in enumerate(lines, start=1)}
        assert at["e01"] == 1 and at["e02"] == 16
        assert {at["e03"], at["e04"]} == {8, 9}
        # 5-8: bottom of the odd-numbered quarters (4, 12) and top of the even-numbered ones (5, 13).
        assert {at[s] for s in seeds[4:]} == {4, 5, 12, 13}


def test_more_seeds_than_first_round_matches_or_unknown_seeds_are_refused():
    with pytest.raises(draws.DrawError):
        draws.build("knockout", ids(6), ids(6)[:5], 1)
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
    return [
        enter(staff, cup, event, player_ids=[str(player(f"{event['name']}{n}").id)]) for n in range(count)
    ]


def test_staff_preview_and_publish_a_draw_and_everyone_sees_the_published_one(staff, cup):
    singles = cup["events"][0]
    entries = fill(staff, cup, singles, 6)
    viewer = logged_in(player("Viewer"))
    assert viewer.get(draw_url(cup, singles)).json() == {"published": None, "preview": None}

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
    assert viewer.get(draw_url(cup, singles)).json() == {"published": None, "preview": None}
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
        "groups", "places", "matches",
    }  # fmt: skip
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
        drawing.record_winner(bye, seed)
    with pytest.raises(Exception, match="aren't known yet"):
        drawing.record_winner(final, seed)
    with pytest.raises(Exception, match="one of the two sides"):
        drawing.record_winner(semi, seed)

    drawing.record_winner(semi, semi.entry_b)
    final.refresh_from_db()
    assert final.entry_b == semi.entry_b and final.status == "scheduled"
    drawing.record_winner(final, seed)
    final.refresh_from_db()
    assert final.winner == seed and final.status == "completed"
    with pytest.raises(Exception, match="already decided"):
        drawing.record_winner(final, seed)


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
    refused(singles, "draw_not_possible", seeded_entry_ids=[entries[0]["id"], entries[1]["id"]])
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
