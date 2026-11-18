"""The official results of matches and rubbers as a history (REQ-015): every version is kept, one
stands. Writing a version also writes, in the same transaction, the job that does what follows from
it (ratings and notifications hang their work on `PROJECTIONS` as they arrive)."""

from collections.abc import Callable

from django.utils import timezone

from core.exceptions import ApiException
from outbox import service as outbox

from .models import Entry, Match, OfficialResult, Resolution, Rubber

Source = OfficialResult.Source

# Functions called with a result once it stands or stops standing. Each must be safe to run twice.
PROJECTIONS: list[Callable[[OfficialResult], None]] = []


def current(match: Match, rubber: Rubber | None = None) -> OfficialResult | None:
    return OfficialResult.objects.filter(match=match, rubber=rubber, current=True).first()


def accept(
    match: Match,
    rubber: Rubber | None,
    winner: Entry,
    outcome: str,
    games,
    *,
    actor=None,
    source: str = Source.UMPIRE,
    reason: str = "",
) -> OfficialResult:
    """Write the next version of the result and make it the one that stands. Call inside the
    transaction that changes the match."""
    earlier = list(OfficialResult.objects.filter(match=match, rubber=rubber).order_by("version"))
    standing = next((result for result in earlier if result.current), None)
    if standing:
        standing.current = False
        standing.save(update_fields=["current"])
        _project(standing)  # what followed from it has to be taken back
    result = OfficialResult.objects.create(
        match=match,
        rubber=rubber,
        version=len(earlier) + 1,
        winner=winner,
        outcome=outcome,
        games=[list(game) for game in games],
        source=source,
        reason=reason,
        recorded_by=actor,
        # A match played again after its result was struck out starts a new history of its own.
        first_accepted_at=standing.first_accepted_at if standing else timezone.now(),
    )
    _project(result)
    return result


def strike_out(result: OfficialResult) -> None:
    """The result no longer stands and nothing replaces it: its match is to be played again."""
    result.current = False
    result.voided_at = timezone.now()
    result.projected_at = None
    result.save(update_fields=["current", "voided_at", "projected_at"])
    _project(result)


def _project(result: OfficialResult) -> None:
    # One job per state of a result: a retry of the same change writes nothing new.
    state = "struck" if result.voided_at else "stands" if result.current else "replaced"
    outbox.enqueue("result.project", f"result:{result.id}:{state}", {"result_id": str(result.id)})


@outbox.handler("result.project")
def project(payload: dict) -> None:
    # NO KEY: rows written by a projection may point at this result while another worker holds it.
    result = OfficialResult.objects.select_for_update(no_key=True).filter(pk=payload["result_id"]).first()
    if result is None:  # its draw was deleted since
        return
    for projection in PROJECTIONS:
        projection(result)
    result.projected_at = timezone.now()
    result.save(update_fields=["projected_at"])


def ensure_not_held(match: Match) -> None:
    """A match whose opponent is in question after a correction is not played on until that is settled."""
    if Resolution.objects.filter(match=match, resolved_at__isnull=True).exists():
        raise ApiException(
            "held_for_correction",
            "An earlier result was corrected, and the organizers haven't yet decided what happens to this "
            "match.",
            409,
        )


def title(entry: Entry | None) -> str:
    """An entry as people call it: the team's name, or its players."""
    if entry is None:
        return ""
    return entry.team_name or " / ".join(place.user.display_name for place in entry.players.all())


def describe(result: OfficialResult) -> dict:
    """One version of a result as OfficialResultSerializer shows it."""
    return {
        "id": result.id,
        "version": result.version,
        "rubber": result.rubber.position if result.rubber_id else None,
        "winner_id": result.winner_id,
        "winner": title(result.winner),
        "outcome": result.outcome,
        "games": result.games,
        "source": result.source,
        "reason": result.reason,
        "recorded_by": result.recorded_by.display_name if result.recorded_by else "",
        "accepted_at": result.accepted_at,
        "current": result.current,
        "struck_out": result.voided_at is not None,
        # What follows from it (ratings, notifications) is still being worked out.
        "processing": result.current and result.projected_at is None,
    }


def history(match: Match) -> list[dict]:
    """Every version of the match's result and of its rubbers' results, oldest first."""
    found = match.results.select_related("winner", "rubber", "recorded_by").prefetch_related(
        "winner__players__user"
    )
    return [describe(result) for result in found.order_by("accepted_at", "version")]
