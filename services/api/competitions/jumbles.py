"""Jumbles (TASK-100): a mixed-doubles round robin. Players enter alone, in the men's or the women's
pool, and the pools must be the same size. Every round each man plays with a different woman, the
pairs meet as in a round robin of the men, and the final table ranks each player by the points they
scored over all their matches.

With n men and n women the men meet in the usual circle rounds (n - 1 rounds, or n when n is odd and
one pair sits each round out), and man i partners woman i + r in round r, so nobody has the same
partner twice. Each round's pairs are kept as entries with the status `pairing`, made by the draw and
removed with it; matches are between pairings, so tables, scoring and results treat them like any
doubles match.
"""

import random

from django.utils import timezone

from core.exceptions import ApiException

from . import draws, standings
from .models import DrawPlace, DrawVersion, Entry, EntryPlayer, Event, Match

P = Entry.Pool


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def pools(event: Event) -> tuple[list[Entry], list[Entry]]:
    accepted = list(
        event.entries.filter(status=Entry.Status.ACCEPTED)
        .prefetch_related("players")
        .order_by("created_at", "id")
    )
    return [e for e in accepted if e.pool == P.MEN], [e for e in accepted if e.pool == P.WOMEN]


def make_draw(event: Event, actor, rng_seed: int, version: int, rules_version: str) -> DrawVersion:
    men, women = pools(event)
    if len(men) != len(women):
        raise _conflict(
            "jumbles_unbalanced",
            f"Jumbles needs as many women as men: {len(men)} men and {len(women)} women are accepted.",
        )
    if len(men) < 2:
        raise _conflict("draw_not_possible", "Jumbles needs at least two men and two women.")
    rng = random.Random(rng_seed)
    rng.shuffle(men)
    rng.shuffle(women)
    draw = DrawVersion.objects.create(
        event=event,
        version=version,
        rules_version=rules_version,
        rng_seed=rng_seed,
        format=event.format,
        group_count=None,
        qualifiers_per_group=None,
        created_by=actor,
    )
    DrawPlace.objects.bulk_create(
        DrawPlace(draw=draw, entry=entry, group=1, group_position=position)
        for position, entry in enumerate([*men, *women], start=1)
    )
    count = len(men)
    now = timezone.now()

    def pairing(man: Entry, woman: Entry) -> Entry:
        made = Entry.objects.create(
            event=event,
            status=Entry.Status.PAIRING,
            pairing_draw=draw,
            entered_by=actor,
            decided_at=now,
            decided_by=actor,
        )
        EntryPlayer.objects.bulk_create(
            EntryPlayer(
                entry=made, event=event, user_id=entry.players.all()[0].user_id, position=index, live=False
            )
            for index, entry in enumerate((man, woman))
        )
        return made

    for number, pairs in enumerate(draws.round_robin(count), start=1):
        # Man i partners woman i + (round - 1): a different woman every round.
        partner = {i: women[(i - 1 + number - 1) % count] for i in range(1, count + 1)}
        for position, (i, j) in enumerate(pairs, start=1):
            Match.objects.create(
                draw=draw,
                stage=Match.Stage.GROUP,
                group=1,
                round=number,
                position=position,
                entry_a=pairing(men[i - 1], partner[i]),
                entry_b=pairing(men[j - 1], partner[j]),
            )
    return draw


def drop(draw: DrawVersion) -> None:
    """Delete a draw with its matches and the pairings it made; matches go first, since they hold the
    pairings."""
    draw.matches.all().delete()
    Entry.objects.filter(pairing_draw=draw).delete()
    draw.delete()


def table(draw: DrawVersion) -> tuple[list[standings.Row], bool]:
    """Every player of the draw, ranked by the points they scored, then matches won, then points
    scored less points conceded. Players nothing separates share a rank."""
    places = list(draw.places.order_by("group_position").prefetch_related("entry__players"))
    rows = {str(place.entry_id): standings.Row(member=str(place.entry_id)) for place in places}
    member_of = {
        player.user_id: str(place.entry_id) for place in places for player in place.entry.players.all()
    }
    matches = list(draw.matches.prefetch_related("entry_a__players", "entry_b__players"))
    for match in matches:
        if match.status != Match.Status.COMPLETED:
            continue
        walkover = match.outcome == Match.Outcome.WALKOVER
        for side, entry in (("a", match.entry_a), ("b", match.entry_b)):
            won = match.winner_id == entry.id
            mine = [game[0] if side == "a" else game[1] for game in match.games]
            theirs = [game[1] if side == "a" else game[0] for game in match.games]
            for place in entry.players.all():
                row = rows[member_of[place.user_id]]
                row.played += 1
                row.won += won
                row.lost += not won
                row.match_points += 2 if won else (0 if walkover else 1)
                row.games_won += sum(1 for us, them in zip(mine, theirs, strict=True) if us > them)
                row.games_lost += sum(1 for us, them in zip(mine, theirs, strict=True) if us < them)
                row.points_won += sum(mine)
                row.points_lost += sum(theirs)
    complete = all(match.status == Match.Status.COMPLETED for match in matches)

    def key(row: standings.Row) -> tuple:
        return (-row.points_won, -row.won, -(row.points_won - row.points_lost))

    ranked = sorted(rows.values(), key=lambda row: (*key(row), list(rows).index(row.member)))
    for index, row in enumerate(ranked):
        before = ranked[index - 1] if index else None
        row.rank = before.rank if before and key(before) == key(row) else index + 1
        row.level = any(key(other) == key(row) for other in ranked if other is not row)
    return ranked, complete


def placements(draw: DrawVersion) -> list[dict]:
    """The winner, or joint winners, once every match is played."""
    rows, complete = table(draw)
    if not complete or not rows:
        return []
    return [{"label": "Winner", "entry_ids": [row.member for row in rows if row.rank == 1]}]


def checked_in(entry: Entry) -> bool:
    """A pairing has arrived when both its players' own entries are checked in."""
    if entry.status != Entry.Status.PAIRING:
        return entry.checked_in_at is not None
    users = [place.user_id for place in entry.players.all()]
    return not Entry.objects.filter(
        event_id=entry.event_id,
        status=Entry.Status.ACCEPTED,
        players__user_id__in=users,
        checked_in_at__isnull=True,
    ).exists()
