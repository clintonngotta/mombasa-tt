"""Draw generation (REQ-009), as pure functions of the entries, the seeds and a seed number.

Rules: ITTF Statutes 2026, Chapter 3 (see rules.py and the transcription in spec.md).

- Knockout: the first round has a power-of-2 number of places (3.6.1.1); seed 1 goes at the top, seed 2
  at the bottom and later seeds are drawn among the places 3.6.2.3 names for them; byes go first
  against the seeded places, in seeding order, and then as evenly as possible (3.6.1.2).
- Round robin: everybody in the group plays everybody else once (3.7.5.1); the last round holds the
  match between the numbers either side of the qualifying line (3.7.5.5).
- Groups then knockout: seeds are spread over the groups in a snake, the rest drawn in; group winners
  take the seeded places of the knockout and a runner-up is drawn into the half away from the winner
  of their own group.
- Spreading (user decision, 2026-11-27): the organizers choose whether clubs, teams and regions are
  kept apart and how many of one a group may hold (three unless they say otherwise); one with too
  many entries to fit may have its fair share in a group.

Nothing here touches the database, so the same inputs always give the same draw.
"""

import math
import random
from dataclasses import dataclass, field

# The longest seed list a request may carry: a bound on the size of a request, not a rule of play.
# Every entry of an event may be seeded, whatever its format.
MAX_SEEDS = 1024


# The most entries of one club, team or region a group may hold unless the organizers choose another
# number (user decision, 2026-11-27).
SAME_GROUP_LIMIT = 3

# How many placements the search for a draw within the limit may try before it settles for the
# arrangement closest to it. Enough for any real field; it bounds the time a request can take.
SEARCH_BUDGET = 20_000


class DrawError(ValueError):
    """The entries, seeds or structure can't make a draw; the message says why."""


@dataclass(frozen=True)
class Side:
    """One side of a match: an entry, or who it will be once earlier results are in."""

    entry: str | None = None
    feeder: tuple[int, int] | None = None  # (round, position) of the knockout match whose winner it is
    qualifier: tuple[int, int] | None = None  # (group, rank)


@dataclass(frozen=True)
class PlannedMatch:
    stage: str  # "group" or "knockout"
    group: int | None
    round: int
    position: int
    a: Side
    b: Side | None  # None is a bye: `a` goes through without playing


@dataclass
class Plan:
    seeds: dict[str, int] = field(default_factory=dict)  # entry -> seed number
    groups: list[list[str]] = field(default_factory=list)  # entries of each group, in group-number order
    lines: list[str | None] = field(default_factory=list)  # first knockout round, top to bottom
    matches: list[PlannedMatch] = field(default_factory=list)


def bracket_size(entries: int) -> int:
    size = 2
    while size < entries:
        size *= 2
    return size


def opponent(place: int) -> int:
    """The other line of the same first-round match (places are 1-based)."""
    return place + 1 if place % 2 else place - 1


def seed_tiers(size: int) -> list[list[int]]:
    """The places seeds are drawn among (3.6.2.3): [1], [last], then the bottom of each odd-numbered and
    the top of each even-numbered half, quarter, eighth... Every place is in a first-round match of its
    own, so together the tiers name one line of every match."""
    tiers = [[1], [size]]
    blocks = 2
    while size // blocks >= 4:
        width = size // blocks
        tiers.append([block * width + (width if block % 2 == 0 else 1) for block in range(blocks)])
        blocks *= 2
    return tiers


def _drawn_evenly(places: list[int], rng: random.Random) -> list[int]:
    """A drawn order of a tier's places in which every run from the start is spread as evenly as it can
    be over the halves, quarters, ... of the draw: the two halves take turns (which one first is drawn),
    and so on within each half. Byes that follow this order are even however many there are (3.6.1.2)."""
    if len(places) <= 1:
        return list(places)
    middle = len(places) // 2
    first, second = _drawn_evenly(places[:middle], rng), _drawn_evenly(places[middle:], rng)
    if rng.random() < 0.5:
        first, second = second, first
    return [place for pair in zip(first, second, strict=True) for place in pair]


def _seeded_places(size: int, rng: random.Random) -> list[int]:
    """Seeded places in seeding order, each tier drawn."""
    return [place for tier in seed_tiers(size) for place in _drawn_evenly(tier, rng)]


def knockout_lines(entries: list[str], seeds: list[str], rng: random.Random) -> list[str | None]:
    """The first round, top to bottom; None is a bye.

    The organizers may rank more entries than there are seeded places (half the bracket), up to the
    whole field. Those ranked below the seeded places are not drawn: the best of them meets the lowest
    seed, the next the seed above, and so on, so a fully ranked field gives 1 v last, 2 v last but one."""
    size = bracket_size(len(entries))
    byes = size - len(entries)
    order = _seeded_places(size, rng)
    lines: dict[int, str] = dict(zip(order, seeds, strict=False))
    bye_places = {opponent(place) for place in order[:byes]}
    # No more are ranked than entered, so each of these places is opposite a seed without a bye.
    lines.update((opponent(order[-rank]), entry) for rank, entry in enumerate(seeds[len(order) :], start=1))
    free = [place for place in range(1, size + 1) if place not in lines and place not in bye_places]
    others = [entry for entry in entries if entry not in set(seeds)]
    rng.shuffle(others)
    lines.update(zip(free, others, strict=True))
    return [lines.get(place) for place in range(1, size + 1)]


def round_robin(count: int, qualifiers: int = 1) -> list[list[tuple[int, int]]]:
    """Rounds of (number, number) pairs for a group of `count`, each pair meeting once. The round
    holding `qualifiers` v `qualifiers + 1` is played last (3.7.5.5)."""
    numbers: list[int | None] = list(range(1, count + 1))
    if count % 2:
        numbers.append(None)  # the number drawn against it sits the round out
    half = len(numbers) // 2
    rounds = []
    for _ in range(len(numbers) - 1):
        pairs = [(numbers[i], numbers[-1 - i]) for i in range(half)]
        rounds.append(sorted((min(a, b), max(a, b)) for a, b in pairs if a is not None and b is not None))
        numbers = [numbers[0], numbers[-1], *numbers[1:-1]]
    decider = (qualifiers, qualifiers + 1)
    rounds.sort(key=lambda pairs: decider in pairs)  # stable: only the deciding round moves, to the end
    return rounds


def group_limits(
    affiliations: dict[str, set[str]], groups: int, limit: int = SAME_GROUP_LIMIT
) -> dict[str, int]:
    """The most entries each club, team or region may have in one group: `limit`, or its fair share
    (its entries over the groups, rounded up) when it has too many entries for that."""
    counts: dict[str, int] = {}
    for found in affiliations.values():
        for name in found:
            counts[name] = counts.get(name, 0) + 1
    return {name: max(limit, math.ceil(count / groups)) for name, count in counts.items()}


def over_limit(
    groups: list[list[str]], affiliations: dict[str, set[str]], limit: int = SAME_GROUP_LIMIT
) -> list[tuple[int, str, int, int]]:
    """Each (group number, affiliation, entries of it in the group, its limit) where a group holds more
    of one club, team or region than group_limits allows."""
    limits = group_limits(affiliations, len(groups), limit)
    found = []
    for number, members in enumerate(groups, start=1):
        counts: dict[str, int] = {}
        for entry in members:
            for name in affiliations.get(entry, ()):
                counts[name] = counts.get(name, 0) + 1
        found += [
            (number, name, count, limits[name])
            for name, count in sorted(counts.items())
            if count > limits[name]
        ]
    return found


def split_into_groups(
    entries: list[str],
    seeds: list[str],
    count: int,
    rng: random.Random,
    affiliations: dict[str, set[str]] | None = None,
    limit: int = SAME_GROUP_LIMIT,
) -> list[list[str]]:
    """Seeds in a snake across the groups (1..n, then n..1, ...), the rest drawn into the same snake, so
    group sizes differ by one at most and each group's numbers follow its seeds. When that breaks the
    limit on one club, team or region in a group, the unseeded entries are drawn again within it,
    keeping the seeds and the group sizes; if no arrangement keeps to it, the closest one is kept."""
    others = [entry for entry in entries if entry not in set(seeds)]
    rng.shuffle(others)
    slots = [
        column if row % 2 == 0 else count - 1 - column
        for row, column in (divmod(i, count) for i in range(len(entries)))
    ]
    groups: list[list[str]] = [[] for _ in range(count)]
    for index, entry in enumerate([*seeds, *others]):
        groups[slots[index]].append(entry)
    if not affiliations or count < 2 or not over_limit(groups, affiliations, limit):
        return groups
    return _spread(seeds, others, slots, count, rng, affiliations, limit)


def _spread(
    seeds: list[str],
    others: list[str],
    slots: list[int],
    count: int,
    rng: random.Random,
    affiliations: dict[str, set[str]],
    limit: int,
) -> list[list[str]]:
    """The draw again so that no group goes over its limits, by a depth-first search with a bounded
    number of steps. The top seeds (one for each group) stay where the snake put them. Each later band
    of seeds (the next one for each group) may change groups within the band, so every group still has
    one seed of each band, the snake's group tried first. Unseeded entries go to any group with room,
    the hardest to place first and the groups in a drawn order. Each group keeps the size the snake
    gave it."""
    limits = group_limits(affiliations, count, limit)
    held: list[dict[str, int]] = [{} for _ in range(count)]
    room = [0] * count
    for slot in slots:
        room[slot] += 1
    where: dict[str, int] = {}
    band_of: dict[str, int] = {}
    band_used: set[tuple[int, int]] = set()  # (band, group) already holding a seed of that band
    choices: dict[str, list[int]] = {}

    def place(entry: str, group: int, step: int) -> None:
        room[group] -= step
        for name in affiliations.get(entry, ()):
            held[group][name] = held[group].get(name, 0) + step
        if entry in band_of:
            (band_used.add if step > 0 else band_used.discard)((band_of[entry], group))
        if step > 0:
            where[entry] = group
        else:
            del where[entry]

    for index, seed in enumerate(seeds):
        band = index // count
        if band == 0:
            place(seed, slots[index], 1)
            continue
        band_of[seed] = band
        groups = [slots[j] for j in range(band * count, min((band + 1) * count, len(seeds)))]
        rest = [group for group in groups if group != slots[index]]
        rng.shuffle(rest)
        # A band the seeds don't fill shares its places with the unseeded entries drawn after them.
        choices[seed] = (
            [slots[index], *rest]
            if len(groups) == count
            else [slots[index], *rng.sample(range(count), count)]
        )

    totals: dict[str, int] = {}
    for found in affiliations.values():
        for name in found:
            totals[name] = totals.get(name, 0) + 1

    def tightness(entry: str) -> float:
        return max((totals[name] / limits[name] for name in affiliations.get(entry, ())), default=0)

    for entry in others:
        choices[entry] = rng.sample(range(count), count)
    # Seeds band by band, then the unseeded hardest first (stable: the drawn order breaks ties).
    order = [seed for seed in seeds if seed in choices] + sorted(others, key=tightness, reverse=True)
    steps = 0

    def open_to(entry: str, group: int) -> bool:
        return room[group] > 0 and (entry not in band_of or (band_of[entry], group) not in band_used)

    def fits(entry: str, group: int) -> bool:
        return open_to(entry, group) and all(
            held[group].get(name, 0) < limits[name] for name in affiliations.get(entry, ())
        )

    def search(index: int) -> bool:
        nonlocal steps
        if index == len(order):
            return True
        entry = order[index]
        for group in dict.fromkeys(choices[entry]):
            steps += 1
            if steps > SEARCH_BUDGET:
                return False
            if fits(entry, group):
                place(entry, group, 1)
                if search(index + 1):
                    return True
                place(entry, group, -1)
        return False

    if not search(0):
        # Nothing within the limit was found (the search undoes every placement it tries): each entry
        # goes where it adds least over the limit, and the organizers move entries by hand, since
        # publication is refused while a group is over.
        for entry in order:
            open_groups = [group for group in dict.fromkeys(choices[entry]) if open_to(entry, group)]
            group = min(
                open_groups,
                key=lambda g: sum(
                    held[g].get(name, 0) >= limits[name] for name in affiliations.get(entry, ())
                ),
            )
            place(entry, group, 1)
    return [[entry for entry in [*seeds, *others] if where[entry] == group] for group in range(count)]


def qualifier_lines(groups: int, per_group: int, rng: random.Random) -> list[tuple[int, int] | None]:
    """The first knockout round for group qualifiers, as (group, rank) or None for a bye. Winners take
    the seeded places in group order; byes go to the best qualifiers first; a lower qualifier is drawn
    into the half away from its own group's winner where there is room."""
    total = groups * per_group
    size = bracket_size(total)
    byes = size - total
    seeded = _seeded_places(size, rng)
    lines: dict[int, tuple[int, int]] = {}
    closed: set[int] = set()  # bye places
    winner_half: dict[int, bool] = {}

    def free(place: int) -> bool:
        return place not in lines and place not in closed

    for rank in range(1, per_group + 1):
        for group in range(1, groups + 1):
            open_places = [place for place in range(1, size + 1) if free(place)]
            if byes:  # this qualifier gets a bye, so it needs a match nobody is in yet
                open_places = [place for place in open_places if free(opponent(place))]
            if rank == 1:
                choices = [place for place in seeded if place in open_places][:1] or open_places
            else:
                # Away from the group's winner where there is room, and never straight into a match
                # against somebody from the same group while another place is open.
                apart = [place for place in open_places if lines.get(opponent(place), (0, 0))[0] != group]
                away = [place for place in apart if (place > size // 2) != winner_half[group]]
                choices = away or apart or open_places
            place = rng.choice(choices)
            lines[place] = (group, rank)
            if rank == 1:
                winner_half[group] = place > size // 2
            if byes:
                closed.add(opponent(place))
                byes -= 1
    return [lines.get(place) for place in range(1, size + 1)]


def knockout_matches(first_round: list[Side | None]) -> list[PlannedMatch]:
    """Every round of a knockout from its first-round lines. A bye's entry is written straight into the
    next round when it is already known."""
    matches = []
    sides = first_round
    round_number = 1
    while len(sides) >= 2:
        next_sides: list[Side | None] = []
        for position in range(1, len(sides) // 2 + 1):
            a, b = sides[2 * position - 2], sides[2 * position - 1]
            if a is None:
                a, b = b, None
            assert a is not None, "a first-round match can't be two byes"
            matches.append(PlannedMatch("knockout", None, round_number, position, a, b))
            through_bye = b is None and a.entry is not None
            next_sides.append(a if through_bye else Side(feeder=(round_number, position)))
        sides = next_sides
        round_number += 1
    return matches


def group_matches(group: int, members: list[str], qualifiers: int) -> list[PlannedMatch]:
    return [
        PlannedMatch("group", group, round_number, position, Side(members[a - 1]), Side(members[b - 1]))
        for round_number, pairs in enumerate(round_robin(len(members), qualifiers), start=1)
        for position, (a, b) in enumerate(pairs, start=1)
    ]


def build(
    event_format: str,
    entries: list[str],
    seeds: list[str],
    rng_seed: int,
    *,
    group_count: int | None = None,
    qualifiers_per_group: int | None = None,
    affiliations: dict[str, set[str]] | None = None,
    limit: int = SAME_GROUP_LIMIT,
) -> Plan:
    """The whole draw for an event format ("knockout", "round_robin" or "groups_knockout").
    `affiliations` names each entry's clubs, teams and region to keep apart, at most `limit` of one in
    a group."""
    entries = sorted(entries)  # the caller's order must not matter
    if len(entries) < 2:
        raise DrawError("A draw needs at least two accepted entries.")
    if len(set(seeds)) != len(seeds) or not set(seeds) <= set(entries):
        raise DrawError("Seeds are accepted entries of this event, each listed once.")
    rng = random.Random(rng_seed)
    plan = Plan(seeds={entry: number for number, entry in enumerate(seeds, start=1)})

    if event_format == "knockout":
        plan.lines = knockout_lines(entries, seeds, rng)
        plan.matches = knockout_matches([Side(entry) if entry else None for entry in plan.lines])
    elif event_format == "round_robin":
        plan.groups = split_into_groups(entries, seeds, 1, rng)
        plan.matches = group_matches(1, plan.groups[0], 1)
    elif event_format == "groups_knockout":
        if not group_count or not qualifiers_per_group:
            raise DrawError("Set the number of groups and qualifiers first.")
        if len(entries) < group_count * (qualifiers_per_group + 1):
            raise DrawError(
                f"{group_count} groups sending {qualifiers_per_group} through need at least "
                f"{group_count * (qualifiers_per_group + 1)} accepted entries."
            )
        plan.groups = split_into_groups(entries, seeds, group_count, rng, affiliations, limit)
        for number, members in enumerate(plan.groups, start=1):
            plan.matches += group_matches(number, members, qualifiers_per_group)
        qualifiers = qualifier_lines(group_count, qualifiers_per_group, rng)
        plan.matches += knockout_matches([Side(qualifier=q) if q else None for q in qualifiers])
    else:
        raise DrawError("Unknown event format.")
    return plan
