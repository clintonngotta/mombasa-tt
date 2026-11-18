"""The rating ledgers (REQ-016): separate singles and doubles Elo over the whole platform.

A ledger is worked out from the official results that stand, in the order each match or rubber first
got an official result, then by its id. That order never changes: a corrected result keeps the place
of the one it replaces. When a result changes, the ledger is cut at that place and written again from
there (`rebuild` with `since`); the same code with no `since` writes it from nothing, and both give
the same numbers.

Rated: completed singles and doubles matches that were played out, including the rubbers of team
ties. Not rated: walkovers, retirements, rubbers that were not played, a tie as a whole, and anything
outside competitions (casual games never get here).
"""

import hashlib
from dataclasses import dataclass

from django.db import connection
from django.db.models import Q

from competitions.models import Event, Match, OfficialResult, RubberPlayer
from outbox.models import Job

from . import elo
from .models import Discipline, Rating, RatingEvent

_GATE = int.from_bytes(hashlib.sha256(b"coast-tt:ratings").digest()[:8], "big", signed=True)


def _lock() -> None:
    """One ledger is written by one transaction at a time; let go when the transaction ends."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_GATE])


@dataclass
class Subject:
    """What a result is about, as the ledger sees it."""

    discipline: str
    id: object  # the rubber's id, or the match's: the stable half of the ledger's order
    sides: dict[str, list]  # user ids on side a and side b


def subject_of(result: OfficialResult) -> Subject | None:
    """The discipline and players of the match or rubber the result belongs to. None for what no
    ledger covers: a team tie as a whole."""
    match = result.match
    if result.rubber_id:
        placed = list(result.rubber.players.all())
        sides = {
            "a": [p.user_id for p in placed if p.side == RubberPlayer.Side.A],
            "b": [p.user_id for p in placed if p.side == RubberPlayer.Side.B],
        }
        return Subject(result.rubber.kind, result.rubber_id, sides)
    if match.draw.event.kind in (Event.Kind.TEAM, Event.Kind.JUMBLES):
        return None  # a tie as a whole, and Jumbles, which no ledger covers
    sides = {
        "a": [place.user_id for place in match.entry_a.players.all()] if match.entry_a_id else [],
        "b": [place.user_id for place in match.entry_b.players.all()] if match.entry_b_id else [],
    }
    return Subject(match.draw.event.kind, match.id, sides)


def _of_discipline(discipline: str) -> Q:
    return Q(rubber__kind=discipline) | Q(rubber__isnull=True, match__draw__event__kind=discipline)


def _rated(discipline: str):
    """The results a ledger is made of: those that stand and were played out."""
    return (
        OfficialResult.objects.filter(_of_discipline(discipline))
        .filter(current=True, voided_at__isnull=True, outcome=Match.Outcome.PLAYED)
        .select_related("match__draw__event", "rubber")
        .prefetch_related("match__entry_a__players", "match__entry_b__players", "rubber__players")
    )


def _from(since) -> Q:
    at, subject_id = since
    return Q(accepted_at__gt=at) | Q(accepted_at=at, subject_id__gte=subject_id)


def rebuild(discipline: str, since=None) -> int:
    """Write the discipline's ledger again from `since` (an `(accepted_at, subject_id)` place in its
    order) to the end, or all of it. Returns how many rating events were written. Call inside a
    transaction."""
    _lock()
    ledger = RatingEvent.objects.filter(discipline=discipline)
    stale = ledger.filter(_from(since)) if since else ledger
    touched = set(stale.values_list("user_id", flat=True))
    stale.delete()
    # Everybody's rating as the ledger left it just before that place.
    standing = {
        user_id: after
        for user_id, after in ledger.order_by("user_id", "-accepted_at", "-subject_id")
        .distinct("user_id")
        .values_list("user_id", "after")
    }
    results = _rated(discipline)
    if since:
        results = results.filter(first_accepted_at__gte=since[0])
    ordered = []
    for result in results:
        subject = subject_of(result)
        place = (result.first_accepted_at, subject.id) if subject else None
        if subject and (since is None or place >= tuple(since)):
            ordered.append((place, result, subject))
    ordered.sort(key=lambda found: found[0])
    made = []
    for (accepted_at, subject_id), result, subject in ordered:
        size = 1 if discipline == Discipline.SINGLES else 2
        if len(subject.sides["a"]) != size or len(subject.sides["b"]) != size:
            continue  # not a complete singles or doubles: nothing to compare
        before = {
            user_id: standing.get(user_id, elo.START) for side in "ab" for user_id in subject.sides[side]
        }
        own = {side: elo.average([before[user_id] for user_id in subject.sides[side]]) for side in "ab"}
        if result.winner_id not in (result.match.entry_a_id, result.match.entry_b_id):
            continue  # the entries of the match changed under an old result: nothing safe to say
        a_won = result.winner_id == result.match.entry_a_id
        delta_a, delta_b, expected_a, expected_b = elo.deltas(
            [before[user_id] for user_id in subject.sides["a"]],
            [before[user_id] for user_id in subject.sides["b"]],
            a_won,
        )
        for side, delta, expected, other in (
            ("a", delta_a, expected_a, "b"),
            ("b", delta_b, expected_b, "a"),
        ):
            for user_id in subject.sides[side]:
                standing[user_id] = before[user_id] + delta
                made.append(
                    RatingEvent(
                        discipline=discipline,
                        user_id=user_id,
                        result=result,
                        match_id=result.match_id,
                        rubber_id=result.rubber_id,
                        accepted_at=accepted_at,
                        subject_id=subject_id,
                        side=side,
                        won=a_won == (side == "a"),
                        before=before[user_id],
                        after=standing[user_id],
                        delta=delta,
                        own=own[side],
                        opponent=own[other],
                        expected=expected,
                    )
                )
    RatingEvent.objects.bulk_create(made, batch_size=500)
    _summarise(discipline, touched | {event.user_id for event in made})
    return len(made)


def _summarise(discipline: str, user_ids: set) -> None:
    """Bring `Rating` in line with the ledger for these players."""
    if not user_ids:
        return
    totals: dict = {}
    events = RatingEvent.objects.filter(discipline=discipline, user_id__in=user_ids).order_by(
        "accepted_at", "subject_id"
    )
    for user_id, won, after in events.values_list("user_id", "won", "after"):
        played, wins, _ = totals.get(user_id, (0, 0, elo.START))
        totals[user_id] = (played + 1, wins + int(won), after)
    Rating.objects.filter(discipline=discipline, user_id__in=user_ids - set(totals)).delete()
    for user_id, (played, wins, after) in totals.items():
        Rating.objects.update_or_create(
            user_id=user_id, discipline=discipline, defaults={"rating": after, "played": played, "won": wins}
        )


def project(result: OfficialResult) -> None:
    """A result started to stand, was replaced or was struck out: write its ledger again from the
    result's place. Doing it twice, or for the replaced and the replacing version in either order,
    gives the same ledger, because only the results that stand now are read."""
    result = (
        OfficialResult.objects.select_related("match__draw__event", "rubber")
        .prefetch_related("match__entry_a__players", "match__entry_b__players", "rubber__players")
        .get(pk=result.pk)
    )
    subject = subject_of(result)
    if subject is None or subject.discipline not in Discipline.values:
        return
    rebuild(subject.discipline, since=(result.first_accepted_at, subject.id))


def pending(discipline: str | None = None) -> bool:
    """Some result that stands has not reached the ledgers yet: what is shown is provisional."""
    # Work the worker still has to do: a job that failed for good is not "processing" any more.
    if not Job.objects.filter(kind="result.project", status=Job.Status.PENDING).exists():
        return False
    # A result that stands, or one struck out for a replay, whose ledger has not been written yet.
    waiting = OfficialResult.objects.filter(
        Q(current=True) | Q(voided_at__isnull=False), projected_at__isnull=True
    )
    if discipline:
        waiting = waiting.filter(_of_discipline(discipline))
    return waiting.exists()
