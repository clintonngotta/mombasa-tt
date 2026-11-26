"""The match-day log (REQ-043): every staff action on match day, with actor, time and reason.

Callers write an entry in the transaction of the action itself, so an action that is rolled back leaves
no entry and an entry always stands for something that happened. The summary is in words as things
stood then (who played, which table), so the log still reads right after later changes.
"""

from realtime import broadcast

from . import official
from .models import Entry, Match, MatchDayLog, Tournament

Action = MatchDayLog.Action


def match_title(match: Match) -> str:
    """ "Men's singles: Amina v Brian"."""
    return f"{match.draw.event.name}: {official.title(match.entry_a)} v {official.title(match.entry_b)}"


def entry_title(entry: Entry) -> str:
    return f"{entry.event.name}: {official.title(entry)}"


def log(
    tournament: Tournament | str,
    action: str,
    summary: str,
    *,
    actor=None,
    match: Match | None = None,
    table=None,
    reason: str = "",
) -> MatchDayLog:
    """Record one action and tell open control centres that the board changed."""
    tournament_id = getattr(tournament, "pk", tournament)
    entry = MatchDayLog.objects.create(
        tournament_id=tournament_id,
        action=action,
        summary=summary[:300],
        actor=actor if actor is not None and actor.is_authenticated else None,
        match=match,
        table=table,
        reason=reason[:300],
    )
    broadcast.tournament_changed(tournament_id, "board")
    return entry


OUTCOME_WORDS = {
    Match.Outcome.PLAYED: "",
    Match.Outcome.WALKOVER: " by walkover",
    Match.Outcome.RETIRED: " by retirement",
    Match.Outcome.DISQUALIFIED: " by disqualification",
}


def result_summary(match: Match, rubber, winner: Entry, outcome: str, games) -> str:
    """ "Men's singles: Amina v Brian, won by Amina by walkover (rubber 2)"."""
    score = ", ".join(f"{a}-{b}" for a, b in games or [])
    where = f" (rubber {rubber.position})" if rubber is not None else ""
    shown = f" {score}" if score else ""
    return (
        f"{match_title(match)}{where}, won by {official.title(winner)}{OUTCOME_WORDS.get(outcome, '')}{shown}"
    )
