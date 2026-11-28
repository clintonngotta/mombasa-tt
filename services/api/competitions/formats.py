"""How many games each match of an event is played over (user request, 2026-11-28).

An event has one `best_of`, and may play longer matches as it goes on: best of 3 in the groups, best
of 5 from the quarter-finals, best of 7 in the final. `Event.best_of_by_stage` names the stages that
change. A knockout stage not named plays as the stage before it, so "5 from the quarter-finals" needs
only the quarter-finals named; the groups and the first knockout rounds fall back to `best_of`.
"""

from django.db.models import Max

from .models import Event, Match

BEST_OF = (3, 5, 7)
GROUP, EARLY, QUARTER, SEMI, FINAL = "group", "knockout", "quarter_final", "semi_final", "final"
# Knockout stages in playing order: each falls back to the one before it.
KNOCKOUT_STAGES = (EARLY, QUARTER, SEMI, FINAL)
STAGE_KEYS = (GROUP, *KNOCKOUT_STAGES)
STAGE_LABELS = {
    GROUP: "Groups",
    EARLY: "Knockout rounds before the quarter-finals",
    QUARTER: "Quarter-finals",
    SEMI: "Semi-finals",
    FINAL: "Final",
}


def stage_problem(value) -> str:
    """Why this can't be an event's best_of_by_stage, or an empty string."""
    if not isinstance(value, dict):
        return "Give each stage's best of as a number."
    for key, games in value.items():
        if key not in STAGE_KEYS:
            return f"Unknown stage: {key}."
        if type(games) is not int or games not in BEST_OF:
            return "Matches are best of 3, 5 or 7."
    return ""


def knockout_stage(round_number: int, rounds: int) -> str:
    """The stage of a knockout round, counted back from the final."""
    left = rounds - round_number
    return {0: FINAL, 1: SEMI, 2: QUARTER}.get(left, EARLY)


def best_of_at(event: Event, stage: str) -> int:
    """The best of for a stage of this event, following the fallbacks."""
    rules = event.best_of_by_stage or {}
    if stage == GROUP:
        return rules.get(GROUP, event.best_of)
    for earlier in reversed(KNOCKOUT_STAGES[: KNOCKOUT_STAGES.index(stage) + 1]):
        if earlier in rules:
            return rules[earlier]
    return event.best_of


def knockout_rounds(match: Match) -> int:
    rounds = getattr(match, "_knockout_rounds", None)
    if rounds is None:
        found = Match.objects.filter(draw_id=match.draw_id, stage=Match.Stage.KNOCKOUT).aggregate(
            most=Max("round")
        )
        rounds = match._knockout_rounds = found["most"] or match.round
    return rounds


def best_of_for(match: Match, event: Event | None = None) -> int:
    """The best of a match (or every rubber of a tie) is played over."""
    event = event or match.draw.event
    if not event.best_of_by_stage:
        return event.best_of
    if match.stage != Match.Stage.KNOCKOUT:
        return best_of_at(event, GROUP)
    return best_of_at(event, knockout_stage(match.round, knockout_rounds(match)))


def prime(matches) -> None:
    """Load the knockout round counts of these matches' draws in one query, for callers that ask the
    best of many matches (the scheduler)."""
    draws = {match.draw_id for match in matches if match.stage == Match.Stage.KNOCKOUT}
    if not draws:
        return
    found = dict(
        Match.objects.filter(draw_id__in=draws, stage=Match.Stage.KNOCKOUT)
        .values("draw_id")
        .annotate(most=Max("round"))
        .values_list("draw_id", "most")
    )
    for match in matches:
        if match.stage == Match.Stage.KNOCKOUT:
            match._knockout_rounds = found.get(match.draw_id) or match.round
