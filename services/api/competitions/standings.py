"""Group ranking (REQ-010), as pure functions of the results.

Rules: ITTF Statutes 2026, 3.7.5 (transcribed in spec.md).

- 3.7.5.1: 2 match points for a win, 1 for a loss in a played match, 0 for a loss in an unplayed or
  unfinished match; ranking is first by match points.
- 3.7.5.2: members level on match points are separated only by the matches between them, taking in
  turn match points, the ratio of wins to losses in individual matches (team events), in games and in
  points, as far as needed.
- 3.7.5.3: as soon as a step settles some members while others stay level, those still level start
  again from match points on the matches among themselves alone.
- 3.7.5.4: what can't be separated is decided by lot.

Ratios are compared exactly, as fractions: a rounded ratio never decides anything.
"""

import random
from dataclasses import dataclass, field
from fractions import Fraction

PLAYED, WALKOVER, RETIRED, DISQUALIFIED = "played", "walkover", "retired", "disqualified"
GAME_POINTS = 11

MEASURES = ("match_points", "rubbers", "games", "points")


@dataclass(frozen=True)
class Result:
    """A decided group match. `games` are (winner's points, loser's points) as recorded; for a walkover
    there are none, for a retirement or a disqualification only what was played."""

    winner: str
    loser: str
    outcome: str = PLAYED
    games: tuple[tuple[int, int], ...] = ()
    best_of: int = 5
    rubbers: tuple[int, int] | None = None  # team ties: individual matches won by winner and loser


@dataclass
class Step:
    """One comparison that involved a member: who it was level with, on what, and its own value."""

    among: tuple[str, ...]
    measure: str  # "match_points", "rubbers", "games", "points" or "lot"
    value: str  # "3", "5/3"; empty for the lot


@dataclass
class Row:
    member: str
    rank: int = 0
    played: int = 0
    won: int = 0
    lost: int = 0
    match_points: int = 0
    games_won: int = 0
    games_lost: int = 0
    points_won: int = 0
    points_lost: int = 0
    level: bool = False  # still level with the row next to it (a group that isn't finished)
    steps: list[Step] = field(default_factory=list)


def credited_games(result: Result) -> list[tuple[int, int]]:
    """Games as they count in the ratios, from the winner's side. A match that wasn't played or wasn't
    finished is completed in the winner's favour: the game in progress to 11 (or two clear) and the
    games still needed at 11-0."""
    needed = result.best_of // 2 + 1
    if result.outcome == PLAYED:
        return list(result.games)
    games = list(result.games)
    if result.outcome in (RETIRED, DISQUALIFIED) and games:
        mine, theirs = games[-1]
        if not (mine >= GAME_POINTS and mine - theirs >= 2) and not (
            theirs >= GAME_POINTS and theirs - mine >= 2
        ):
            games[-1] = (max(GAME_POINTS, theirs + 2), theirs)  # the unfinished game goes to the winner
    won = sum(1 for mine, theirs in games if mine > theirs)
    return games + [(GAME_POINTS, 0)] * (needed - won)


class _Tally:
    """Wins, losses and the three measures of one member over a set of matches."""

    def __init__(self):
        self.played = self.won = self.lost = self.match_points = 0
        self.for_ = {"rubbers": 0, "games": 0, "points": 0}
        self.against = {"rubbers": 0, "games": 0, "points": 0}

    def add(self, result: Result, winner: bool) -> None:
        self.played += 1
        self.won += winner
        self.lost += not winner
        if winner:
            self.match_points += 2
        elif result.outcome == PLAYED:
            self.match_points += 1
        games = credited_games(result)
        mine = (
            sum(1 for a, b in games if a > b),
            sum(a for a, _ in games),
            result.rubbers[0] if result.rubbers else 0,
        )
        theirs = (
            sum(1 for a, b in games if b > a),
            sum(b for _, b in games),
            result.rubbers[1] if result.rubbers else 0,
        )
        if not winner:
            mine, theirs = theirs, mine
        for name, index in (("games", 0), ("points", 1), ("rubbers", 2)):
            self.for_[name] += mine[index]
            self.against[name] += theirs[index]

    def key(self, measure: str):
        """Something that sorts higher for the better member. A ratio with nothing lost beats any other."""
        if measure == "match_points":
            return self.match_points
        won, lost = self.for_[measure], self.against[measure]
        if lost == 0:
            return (1, Fraction(won)) if won else (0, Fraction(0))
        return (0, Fraction(won, lost))

    def shown(self, measure: str) -> str:
        if measure == "match_points":
            return str(self.match_points)
        return f"{self.for_[measure]}/{self.against[measure]}"


def _tallies(members, results: list[Result], forfeited: set[str]) -> dict[str, _Tally]:
    """Tallies over the matches among `members` only. A member who forfeited loses every match unplayed,
    whatever happened at the table (3.7.5.1); two who both forfeited score nothing against each other."""
    inside = set(members)
    tallies = {member: _Tally() for member in members}
    for result in results:
        winner, loser = result.winner, result.loser
        if winner not in inside or loser not in inside:
            continue
        if winner in forfeited or loser in forfeited:
            if winner in forfeited and loser in forfeited:
                continue
            if winner in forfeited:
                winner, loser = loser, winner
            result = Result(winner, loser, WALKOVER, best_of=result.best_of)
        tallies[winner].add(result, winner=True)
        tallies[loser].add(result, winner=False)
    return tallies


def rank(
    members: list[str],
    results: list[Result],
    *,
    forfeited: frozenset[str] | set[str] = frozenset(),
    final: bool = True,
    lot_seed: int = 0,
    team: bool = False,
) -> list[Row]:
    """The group in ranking order. `members` are in group-number order. While the group isn't finished
    (`final=False`) members nobody can separate yet stay `level` instead of being drawn by lot."""
    forfeited = set(forfeited)
    overall = _tallies(members, results, forfeited)
    rows = {member: Row(member) for member in members}
    for member, tally in overall.items():
        row = rows[member]
        row.played, row.won, row.lost, row.match_points = (
            tally.played,
            tally.won,
            tally.lost,
            tally.match_points,
        )
        row.games_won, row.games_lost = tally.for_["games"], tally.against["games"]
        row.points_won, row.points_lost = tally.for_["points"], tally.against["points"]
    measures = [m for m in MEASURES if team or m != "rubbers"]
    rng = random.Random(lot_seed)

    def separate(level: list[str]) -> list[list[str]]:
        """`level` split into classes, best first; a class of several is still level. The comparisons
        are written to the rows only when they lead somewhere: a split here, or the lot at the end."""
        if len(level) == 1:
            return [level]
        tallies = _tallies(level, results, forfeited)
        tried: list[str] = []
        for measure in measures:
            tried.append(measure)
            classes: dict = {}
            for member in level:
                classes.setdefault(tallies[member].key(measure), []).append(member)
            if len(classes) > 1:
                note(level, tallies, tried)
                # Whoever is still level starts again on the matches among themselves (3.7.5.3).
                return [part for key in sorted(classes, reverse=True) for part in separate(classes[key])]
        if final:
            note(level, tallies, tried)
        return [level]

    def note(level: list[str], tallies: dict[str, _Tally], tried: list[str]) -> None:
        for member in level:
            rows[member].steps += [
                Step(tuple(level), measure, tallies[member].shown(measure)) for measure in tried
            ]

    # First by match points over the whole group (3.7.5.1); then each level set on its own matches.
    by_points: dict[int, list[str]] = {}
    for member in members:
        by_points.setdefault(overall[member].match_points, []).append(member)
    order: list[str] = []
    for points in sorted(by_points, reverse=True):
        for level in separate(by_points[points]):
            if len(level) > 1 and final:
                for member in level:
                    rows[member].steps.append(Step(tuple(level), "lot", ""))
                level = rng.sample(level, len(level))
            elif len(level) > 1:
                for member in level:
                    rows[member].level = True
            order.extend(level)
    for position, member in enumerate(order, start=1):
        rows[member].rank = position
    return [rows[member] for member in order]
