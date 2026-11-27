"""Keeping clubs, teams and regions apart in the groups, and moving entries of a preview by hand
(REQ-009, EVAL-009, TASK-144).

No group holds more than three entries of one club, team or region, unless that one has more entries
than three for each group; then a group holds no more than its fair share (its entries over the groups,
rounded up). The draw keeps to it by itself; the organizers move entries by hand, and a draw over the
limit can't be published.
"""

import random
from collections import Counter

import pytest

from competitions import draws
from competitions.models import DrawVersion, Event, Match
from organizations.models import Organization
from profiles.models import profile_for

from .helpers import logged_in
from .test_draws import cup, draw_url, fill, ids  # noqa: F401 (cup is a fixture)
from .test_entries import act, enter, player
from .test_roles import add_member
from .test_tournaments import url

pytestmark = pytest.mark.django_db


def snake_groups(count: int, total: int) -> list[int]:
    """The group (0-based) each snake place falls in: 0..n-1, then n-1..0, and so on."""
    return [c if r % 2 == 0 else count - 1 - c for r, c in (divmod(i, count) for i in range(total))]


# --- The rule, as pure functions -----------------------------------------------------------------


def test_the_limit_is_three_or_the_fair_share_when_one_has_too_many_entries():
    affiliations = {f"e{n}": {"club"} for n in range(10)} | {"x": {"town"}}
    assert draws.group_limits(affiliations, 4) == {"club": 3, "town": 3}  # 10 entries over 4 groups fit
    assert draws.group_limits(affiliations, 2) == {"club": 5, "town": 3}  # 10 over 2: five a group


@pytest.mark.parametrize("rng_seed", range(30))
def test_the_draw_keeps_one_club_to_three_a_group_and_the_seeds_and_sizes_stay(rng_seed):
    entries = ids(16)
    seeds = entries[:4]
    affiliations = {entry: {"club:bandari"} for entry in entries[4:12]}  # 8 unseeded from one club
    plan = draws.build(
        "groups_knockout",
        entries,
        seeds,
        rng_seed,
        group_count=4,
        qualifiers_per_group=2,
        affiliations=affiliations,
    )
    assert draws.over_limit(plan.groups, affiliations) == []
    assert all(Counter(e in affiliations for e in group)[True] <= 3 for group in plan.groups)
    assert sorted(len(group) for group in plan.groups) == [4, 4, 4, 4]
    assert [group[0] for group in plan.groups] == seeds  # the snake gives seed n to group n
    assert sorted(e for group in plan.groups for e in group) == sorted(entries)


@pytest.mark.parametrize("rng_seed", range(30))
def test_clubs_and_regions_are_kept_apart_together(rng_seed):
    rng = random.Random(rng_seed)
    entries = ids(24)
    clubs = ["club:a", "club:b", "club:c"]
    regions = ["region:ke:mombasa", "region:ke:kilifi"]
    affiliations = {entry: {rng.choice(clubs), rng.choice(regions)} for entry in entries}
    plan = draws.build(
        "groups_knockout",
        entries,
        entries[:6],
        rng_seed,
        group_count=6,
        qualifiers_per_group=1,
        affiliations=affiliations,
    )
    assert draws.over_limit(plan.groups, affiliations) == []
    sizes = Counter(snake_groups(6, 24))
    assert [len(group) for group in plan.groups] == [sizes[g] for g in range(6)]


@pytest.mark.parametrize("rng_seed", range(30))
def test_a_fully_seeded_field_is_kept_apart_by_moving_seeds_within_their_band(rng_seed):
    """Found on a copy of a real event: seeded by rating, every entry is a seed, so nothing unseeded
    can move. The top seeds stay; each later band of seeds changes groups among itself."""
    entries = ids(37)
    rng = random.Random(rng_seed)
    seeds = rng.sample(entries, 37)
    affiliations = {entry: {"club:dev"} for entry in seeds[3:13]} | {
        e: {"region:ke:kilifi"} for e in seeds[13:22]
    }
    plan = draws.build(
        "groups_knockout",
        entries,
        seeds,
        rng_seed,
        group_count=8,
        qualifiers_per_group=2,
        affiliations=affiliations,
        limit=2,
    )
    assert draws.over_limit(plan.groups, affiliations, 2) == []
    assert [group[0] for group in plan.groups] == seeds[:8]  # the top seeds where the snake puts them
    rank = {seed: index for index, seed in enumerate(seeds)}
    for group in plan.groups:
        bands = [rank[entry] // 8 for entry in group]
        assert bands == sorted(set(bands)) and bands[:4] == [0, 1, 2, 3]  # one of each band, in order
    sizes = Counter(snake_groups(8, 37))
    assert [len(group) for group in plan.groups] == [sizes[g] for g in range(8)]


def test_a_draw_already_within_the_limit_is_the_same_as_without_it():
    entries = ids(12)
    spread = {entry: {f"club:{n % 4}"} for n, entry in enumerate(entries)}  # three of each club
    for rng_seed in range(20):
        plain = draws.build(
            "groups_knockout", entries, entries[:3], rng_seed, group_count=3, qualifiers_per_group=1
        )
        kept = draws.build(
            "groups_knockout",
            entries,
            entries[:3],
            rng_seed,
            group_count=3,
            qualifiers_per_group=1,
            affiliations=spread,
        )
        if not draws.over_limit(plain.groups, spread):
            assert kept.groups == plain.groups and kept.lines == plain.lines


def test_a_region_everybody_comes_from_is_no_limit():
    entries = ids(16)
    everybody = {entry: {"region:ke:mombasa"} for entry in entries}
    plan = draws.build(
        "groups_knockout", entries, [], 4, group_count=2, qualifiers_per_group=1, affiliations=everybody
    )
    assert draws.over_limit(plan.groups, everybody) == [] and [len(g) for g in plan.groups] == [8, 8]


def test_without_an_arrangement_found_the_closest_is_kept_and_sizes_stay(monkeypatch):
    monkeypatch.setattr(draws, "SEARCH_BUDGET", 0)
    entries = ids(12)
    affiliations = {entry: {"club:x"} for entry in entries[:8]}
    plan = draws.build(
        "groups_knockout", entries, [], 5, group_count=3, qualifiers_per_group=1, affiliations=affiliations
    )
    assert sorted(e for g in plan.groups for e in g) == sorted(entries)
    assert sorted(len(g) for g in plan.groups) == [4, 4, 4]
    # 8 over 3 groups: the limit is 3, and placing each where it adds least over it keeps to it here.
    assert draws.over_limit(plan.groups, affiliations) == []


# --- The draw desk (API) ---------------------------------------------------------------------------


@pytest.fixture
def bandari(admin):
    from .test_roles import create_club

    return create_club(admin, name="Bandari TT")


def groups_event(staff, cup, count=4):  # noqa: F811
    event = cup["events"][1]
    assert staff.patch(url(cup, event=event), {"group_count": count}, format="json").status_code == 200
    return event


def members_of(club, entries):
    for entry in entries:
        add_member(club, player_of(entry))


def player_of(entry):
    from accounts.models import User

    return User.objects.get(pk=entry["players"][0]["id"])


def club_count(preview, club_ids, group) -> int:
    return sum(1 for p in preview["places"] if p["group"] == group and p["entry"]["id"] in club_ids)


def move(staff, cup, event, expect=200, **body):  # noqa: F811
    response = staff.post(draw_url(cup, event, "move"), body, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def test_the_preview_keeps_a_club_to_three_a_group(staff, cup, bandari):  # noqa: F811
    event = groups_event(staff, cup)
    entries = fill(staff, cup, event, 12)
    members_of(bandari, entries[:6])
    from_bandari = {e["id"] for e in entries[:6]}
    for rng_seed in range(8):
        preview = staff.post(draw_url(cup, event, "preview"), {"rng_seed": rng_seed}, format="json").json()[
            "preview"
        ]
        assert preview["over_limit"] == [] and preview["moved_at"] is None
        assert all(club_count(preview, from_bandari, g) <= 3 for g in (1, 2, 3, 4))
    marked = {p["entry"]["id"]: p["affiliations"] for p in preview["places"]}
    assert all(marked[e] == ["Bandari TT"] for e in from_bandari)
    assert all(marked[e["id"]] == [] for e in entries[6:])


def test_the_region_players_live_in_is_kept_apart_too(staff, cup):  # noqa: F811
    event = groups_event(staff, cup)
    entries = fill(staff, cup, event, 12)
    for entry in entries[:7]:
        profile = profile_for(player_of(entry))
        profile.country, profile.region = "KE", "Kilifi"
        profile.save()
    from_kilifi = {e["id"] for e in entries[:7]}
    preview = staff.post(draw_url(cup, event, "preview"), {"rng_seed": 2}, format="json").json()["preview"]
    assert preview["over_limit"] == []
    assert all(club_count(preview, from_kilifi, g) <= 3 for g in (1, 2, 3, 4))
    assert {p["entry"]["id"]: p["affiliations"] for p in preview["places"]}[entries[0]["id"]] == ["Kilifi"]


def test_staff_move_entries_between_groups_and_a_group_over_the_limit_cant_be_published(
    staff,
    cup,  # noqa: F811
    bandari,
):
    event = groups_event(staff, cup)
    entries = fill(staff, cup, event, 16)
    members_of(bandari, entries[:6])
    from_bandari = {e["id"] for e in entries[:6]}
    preview = staff.post(draw_url(cup, event, "preview"), {"rng_seed": 1}, format="json").json()["preview"]
    group_of = {p["entry"]["id"]: p["group"] for p in preview["places"]}
    # The group with Bandari players in it: bring another one in from elsewhere.
    full = max((1, 2, 3, 4), key=lambda g: club_count(preview, from_bandari, g))
    while club_count(preview, from_bandari, full) < 3:
        mover = next(e for e in from_bandari if group_of[e] != full)
        swap = next(
            p["entry"]["id"]
            for p in preview["places"]
            if p["group"] == full and p["entry"]["id"] not in from_bandari
        )
        preview = move(staff, cup, event, entry_id=mover, swap_with=swap)["preview"]
        group_of = {p["entry"]["id"]: p["group"] for p in preview["places"]}
    fourth = next(e for e in from_bandari if group_of[e] != full)
    other = next(
        p["entry"]["id"]
        for p in preview["places"]
        if p["group"] == full and p["entry"]["id"] not in from_bandari
    )
    shown = move(staff, cup, event, entry_id=fourth, swap_with=other)["preview"]
    assert shown["moved_at"] is not None
    assert shown["over_limit"] == [{"group": full, "name": "Bandari TT", "count": 4, "limit": 3}]
    refused = staff.post(draw_url(cup, event, "publish"), {}, format="json")
    assert refused.status_code == 409 and refused.json()["code"] == "draw_over_limit"
    assert "Bandari TT" in refused.json()["message"]

    # Each group's matches are made again from who is in it now.
    for number in (1, 2, 3, 4):
        members = {p["entry"]["id"] for p in shown["places"] if p["group"] == number}
        played = [m for m in shown["matches"] if m["stage"] == "group" and m["group"] == number]
        assert len(played) == len(members) * (len(members) - 1) // 2
        assert {m["a"]["entry"]["id"] for m in played} | {m["b"]["entry"]["id"] for m in played} == members
        positions = sorted(p["group_position"] for p in shown["places"] if p["group"] == number)
        assert positions == list(range(1, len(members) + 1))
    knockout = [m["id"] for m in shown["matches"] if m["stage"] == "knockout"]
    assert knockout == [m["id"] for m in preview["matches"] if m["stage"] == "knockout"]  # untouched

    back = move(staff, cup, event, entry_id=fourth, swap_with=other)["preview"]
    assert back["over_limit"] == []
    published = staff.post(draw_url(cup, event, "publish"), {}, format="json")
    assert published.status_code == 200 and published.json()["published"]["moved_at"] is not None


def test_moving_into_a_group_keeps_seeds_first_and_a_group_big_enough(staff, cup):  # noqa: F811
    event = groups_event(staff, cup, count=2)
    staff.patch(url(cup, event=event), {"seeding": "manual"}, format="json")
    entries = fill(staff, cup, event, 5)
    seeds = [entries[0]["id"], entries[1]["id"]]
    preview = staff.post(draw_url(cup, event, "preview"), {"seeded_entry_ids": seeds}, format="json").json()[
        "preview"
    ]
    sizes = Counter(p["group"] for p in preview["places"])
    small = min(sizes, key=sizes.get)  # two members: one qualifier needs both
    big = 3 - small
    lonely = next(p for p in preview["places"] if p["group"] == small and not p["seed"])
    tiny = move(staff, cup, event, 409, entry_id=lonely["entry"]["id"], group=big)
    assert tiny["code"] == "group_too_small"

    # Seed 1 moved into the small group, beside seed 2, is number one there and seed 2 number two.
    mover = next(p for p in preview["places"] if p["group"] == big and p["seed"])
    assert mover["seed"] == 1
    after = move(staff, cup, event, entry_id=mover["entry"]["id"], group=small)["preview"]
    in_small = [
        p["entry"]["id"]
        for p in sorted(after["places"], key=lambda p: p["group_position"])
        if p["group"] == small
    ]
    assert in_small[:2] == seeds and len(in_small) == 3
    assert DrawVersion.objects.get(status="preview").moved_by is not None


def test_moves_that_make_no_sense_are_refused(staff, cup):  # noqa: F811
    singles, groups = cup["events"]
    entries = fill(staff, cup, groups, 6)
    assert move(staff, cup, groups, 409, entry_id=entries[0]["id"], group=2)["code"] == "no_preview"
    preview = staff.post(draw_url(cup, groups, "preview"), {"rng_seed": 4}, format="json").json()["preview"]
    place = preview["places"][0]
    mate = next(p for p in preview["places"] if p["group"] == place["group"] and p is not place)
    assert move(staff, cup, groups, 400, entry_id=place["entry"]["id"])["code"] == "validation_error"
    both = move(
        staff, cup, groups, 400, entry_id=place["entry"]["id"], group=1, swap_with=mate["entry"]["id"]
    )
    assert both["code"] == "validation_error"
    assert (
        move(staff, cup, groups, 400, entry_id=place["entry"]["id"], group=place["group"])["code"]
        == "invalid_move"
    )
    assert move(staff, cup, groups, 400, entry_id=place["entry"]["id"], group=3)["code"] == "invalid_move"
    same = move(staff, cup, groups, 400, entry_id=place["entry"]["id"], swap_with=mate["entry"]["id"])
    assert same["code"] == "invalid_move"
    assert (
        move(staff, cup, groups, 400, entry_id=entries[0]["id"], swap_with=singles["id"])["code"]
        == "not_in_draw"
    )

    stranger = logged_in(player("Nosy"))
    assert (
        stranger.post(
            draw_url(cup, groups, "move"), {"entry_id": place["entry"]["id"], "group": 1}, format="json"
        ).status_code
        == 403
    )

    staff.patch(url(cup, event=groups), {"format": "round_robin"}, format="json")
    staff.post(draw_url(cup, groups, "preview"), {}, format="json")
    one = move(staff, cup, groups, 409, entry_id=place["entry"]["id"], swap_with=mate["entry"]["id"])
    assert one["code"] == "not_movable"


def test_staff_swap_two_knockout_lines_and_the_bye_goes_with_the_line(staff, cup):  # noqa: F811
    singles = cup["events"][0]
    entries = fill(staff, cup, singles, 6)
    seeds = [entries[0]["id"], entries[1]["id"]]
    made = staff.post(
        draw_url(cup, singles, "preview"), {"seeded_entry_ids": seeds, "rng_seed": 7}, format="json"
    ).json()
    published_before = staff.post(draw_url(cup, singles, "publish"), {}, format="json").json()["published"]
    preview = staff.post(
        draw_url(cup, singles, "preview"), {"seeded_entry_ids": seeds, "rng_seed": 7}, format="json"
    ).json()["preview"]
    assert made["preview"]["places"] == preview["places"]
    line_of = {p["entry"]["id"]: p["bracket_position"] for p in preview["places"]}
    unseeded = next(e["id"] for e in entries if e["id"] not in seeds)
    assert move(staff, cup, singles, 400, entry_id=seeds[0], group=1)["code"] == "invalid_move"
    shown = move(staff, cup, singles, entry_id=seeds[0], swap_with=unseeded)
    after = shown["preview"]
    moved = {p["entry"]["id"]: p["bracket_position"] for p in after["places"]}
    assert moved[seeds[0]] == line_of[unseeded] and moved[unseeded] == line_of[seeds[0]] == 1
    first = [m for m in after["matches"] if m["round"] == 1]
    bye = first[0]
    assert bye["status"] == "bye" and bye["a"]["entry"]["id"] == unseeded and bye["winner_id"] == unseeded
    assert len(after["matches"]) == 7 and Match.objects.filter(draw__status="preview").count() == 7
    sides = [(m["a"]["entry"]["id"], m["b"]["entry"]["id"]) for m in first if m["b"]]
    assert any(seeds[0] in pair for pair in sides)  # the seed now plays the first round
    # The published draw is not touched by a move in the preview.
    assert shown["published"]["places"] == published_before["places"]
    assert shown["published"]["moved_at"] is None


def test_a_jumbles_draw_isnt_moved_by_hand(staff, cup):  # noqa: F811
    event = Event.objects.get(pk=cup["events"][0]["id"])
    event.kind = Event.Kind.JUMBLES
    event.save(update_fields=["kind"])
    preview = DrawVersion.objects.create(
        event=event, version=1, rules_version="x", rng_seed=1, format=event.format, created_by=None
    )
    assert preview.status == "preview"
    response = move(staff, cup, cup["events"][0], 409, entry_id=str(preview.id), group=1)
    assert response["code"] == "not_movable"


def test_teams_count_as_clubs(staff, cup, admin):  # noqa: F811
    team = Organization.objects.create(name="Wanderers", town="Mombasa", kind=Organization.Kind.TEAM)
    event = groups_event(staff, cup)
    entries = fill(staff, cup, event, 12)
    members_of(team, entries[:5])
    preview = staff.post(draw_url(cup, event, "preview"), {"rng_seed": 9}, format="json").json()["preview"]
    team_ids = {e["id"] for e in entries[:5]}
    assert all(club_count(preview, team_ids, g) <= 3 for g in (1, 2, 3, 4))
    assert {p["entry"]["id"]: p["affiliations"] for p in preview["places"]}[entries[0]["id"]] == ["Wanderers"]


def test_the_organizers_choose_what_is_kept_apart_and_how_many_a_group_may_hold(
    staff,
    cup,  # noqa: F811
    bandari,
):
    event = groups_event(staff, cup)
    entries = fill(staff, cup, event, 16)
    members_of(bandari, entries[:6])
    for entry in entries[8:14]:
        profile = profile_for(player_of(entry))
        profile.country, profile.region = "KE", "Kwale"
        profile.save()
    from_bandari = {e["id"] for e in entries[:6]}
    from_kwale = {e["id"] for e in entries[8:14]}

    def drawn(**body):
        response = staff.post(draw_url(cup, event, "preview"), body, format="json")
        assert response.status_code == 200, response.json()
        return response.json()["preview"]

    # Left out, all three are kept apart, three to a group.
    default = drawn(rng_seed=3)
    assert default["keep_apart"] == ["clubs", "teams", "regions"] and default["same_group_limit"] == 3

    # Two to a group for clubs only: regions are neither kept apart nor shown.
    for rng_seed in range(6):
        two = drawn(rng_seed=rng_seed, keep_apart=["clubs"], same_group_limit=2)
        assert two["keep_apart"] == ["clubs"] and two["same_group_limit"] == 2
        assert all(club_count(two, from_bandari, g) <= 2 for g in (1, 2, 3, 4))
        assert all(p["affiliations"] in ([], ["Bandari TT"]) for p in two["places"])

    # Nothing kept apart: the plain draw, and nothing stops publication however the groups fall.
    free = drawn(rng_seed=3, keep_apart=[])
    assert free["keep_apart"] == [] and all(p["affiliations"] == [] for p in free["places"])
    group_of = {p["entry"]["id"]: p["group"] for p in free["places"]}
    target = group_of[next(iter(from_kwale))]
    while club_count(free, from_kwale, target) < 4:  # four from Kwale in one group
        mover = next(e for e in from_kwale if group_of[e] != target)
        swap = next(
            p["entry"]["id"]
            for p in free["places"]
            if p["group"] == target and p["entry"]["id"] not in from_kwale
        )
        free = move(staff, cup, event, entry_id=mover, swap_with=swap)["preview"]
        group_of = {p["entry"]["id"]: p["group"] for p in free["places"]}
    assert free["over_limit"] == []
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200

    wrong = staff.post(draw_url(cup, event, "preview"), {"keep_apart": ["towns"]}, format="json")
    assert wrong.status_code == 400
    zero = staff.post(draw_url(cup, event, "preview"), {"same_group_limit": 0}, format="json")
    assert zero.status_code == 400


# --- Late entries: from the published draw, one group at a time (TASK-144) -------------------------


def test_a_late_entry_joins_one_group_of_the_published_draw_and_publishes_as_a_new_version(
    staff,
    cup,  # noqa: F811
):
    event = groups_event(staff, cup, count=2)
    fill(staff, cup, event, 8)
    assert staff.post(draw_url(cup, event, "reopen"), {}, format="json").json()["code"] == "no_published_draw"
    staff.post(draw_url(cup, event, "preview"), {"rng_seed": 5}, format="json")
    first = staff.post(draw_url(cup, event, "publish"), {}, format="json").json()["published"]

    late = enter(staff, cup, event, player_ids=[str(player("Latecomer").id)])
    assert staff.get(draw_url(cup, event)).json()["published"]["stale"] is True

    copy = staff.post(draw_url(cup, event, "reopen"), {}, format="json").json()["preview"]

    def where(draw):
        return sorted((p["entry"]["id"], p["group"], p["group_position"], p["seed"]) for p in draw["places"])

    assert where(copy) == where(first) and copy["version"] == 2 and copy["moved_at"]
    assert len(copy["matches"]) == len(first["matches"])
    assert copy["stale"] is True  # it doesn't hold the late entry yet
    assert [m["entry"]["id"] for m in copy["not_in_draw"]] == [late["id"]]
    suggested = copy["not_in_draw"][0]["suggested_group"]
    assert suggested in (1, 2)
    refused = staff.post(draw_url(cup, event, "publish"), {}, format="json")
    assert refused.json()["code"] == "draw_stale"

    other = 3 - suggested
    untouched = sorted(m["id"] for m in copy["matches"] if m["stage"] == "group" and m["group"] == other)
    added = move(staff, cup, event, entry_id=late["id"], group=suggested)["preview"]
    assert added["not_in_draw"] == [] and added["stale"] is False
    members = [p for p in added["places"] if p["group"] == suggested]
    assert len(members) == 5 and max(members, key=lambda p: p["group_position"])["entry"]["id"] == late["id"]
    played = [m for m in added["matches"] if m["stage"] == "group" and m["group"] == suggested]
    assert len(played) == 10
    assert (
        sorted(m["id"] for m in added["matches"] if m["stage"] == "group" and m["group"] == other)
        == untouched
    )

    shown = staff.post(draw_url(cup, event, "publish"), {}, format="json").json()
    assert shown["published"]["version"] == 2 and shown["preview"] is None
    assert DrawVersion.objects.get(pk=first["id"]).status == "superseded"


def test_a_withdrawn_entry_is_taken_out_of_its_group(staff, cup):  # noqa: F811
    event = groups_event(staff, cup, count=2)
    entries = fill(staff, cup, event, 7)
    staff.post(draw_url(cup, event, "preview"), {"rng_seed": 2}, format="json")
    published = staff.post(draw_url(cup, event, "publish"), {}, format="json").json()["published"]
    big = max((1, 2), key=lambda g: sum(p["group"] == g for p in published["places"]))
    leaving = next(p["entry"]["id"] for p in published["places"] if p["group"] == big)
    act(staff, cup, event, {"id": leaving}, "staff-withdraw", reason="Injured")

    copy = staff.post(draw_url(cup, event, "reopen"), {}, format="json").json()["preview"]
    assert [p["entry"]["id"] for p in copy["places"] if p["withdrawn"]] == [leaving]
    still = next(e["id"] for e in entries if e["id"] != leaving)
    assert move(staff, cup, event, 400, entry_id=still, remove=True)["code"] == "invalid_move"
    out = move(staff, cup, event, entry_id=leaving, remove=True)["preview"]
    assert leaving not in {p["entry"]["id"] for p in out["places"]} and out["stale"] is False
    assert sorted(p["group_position"] for p in out["places"] if p["group"] == big) == [1, 2, 3]
    assert len([m for m in out["matches"] if m["stage"] == "group" and m["group"] == big]) == 3
    assert staff.post(draw_url(cup, event, "publish"), {}, format="json").status_code == 200


def test_a_knockout_late_entry_means_drawing_again(staff, cup):  # noqa: F811
    singles = cup["events"][0]
    fill(staff, cup, singles, 4)
    staff.post(draw_url(cup, singles, "preview"), {}, format="json")
    staff.post(draw_url(cup, singles, "publish"), {}, format="json")
    late = enter(staff, cup, singles, player_ids=[str(player("Lateknock").id)])
    staff.post(draw_url(cup, singles, "reopen"), {}, format="json")
    assert move(staff, cup, singles, 409, entry_id=late["id"], group=1)["code"] == "not_addable"
    stranger = logged_in(player("Peeker"))
    assert stranger.post(draw_url(cup, singles, "reopen"), {}, format="json").status_code == 403


def test_two_teams_swap_groups(staff, club):
    from .test_ties import team
    from .test_tournaments import add_event, do, make_tournament
    from .test_venues import make_venue

    tournament = make_tournament(staff, club, make_venue(staff, club))
    add_event(
        staff,
        tournament,
        name="Teams",
        kind="team",
        format="groups_knockout",
        group_count=2,
        qualifiers_per_group=1,
    )
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    teams = [team(staff, tournament, event, f"Side{n}", size=3)[0] for n in range(4)]
    preview = staff.post(draw_url(tournament, event, "preview"), {"rng_seed": 1}, format="json").json()[
        "preview"
    ]
    group_of = {p["entry"]["id"]: p["group"] for p in preview["places"]}
    a = teams[0]["id"]
    b = next(t["id"] for t in teams if group_of[t["id"]] != group_of[a])
    swapped = move(staff, tournament, event, entry_id=a, swap_with=b)["preview"]
    after = {p["entry"]["id"]: p["group"] for p in swapped["places"]}
    assert (after[a], after[b]) == (group_of[b], group_of[a])
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
