"""How many games each match of an event is played over (user request, 2026-11-28).

An event has one `best_of`, and may play longer matches as it goes on: best of 3 in the groups, best
of 5 from the quarter-finals, best of 7 in the final. `Event.best_of_by_stage` names the stages that
change. A knockout stage not named plays as the stage before it, so "5 from the quarter-finals" needs
only the quarter-finals named; the groups and the first knockout rounds fall back to `best_of`.
"""

from django.db.models import Exists, Max, OuterRef, Q

from .models import DrawVersion, Event, Match, Rubber

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
    """The best of a match (or every rubber of a tie) is played over: its own, once frozen, or else
    the event's rule for its stage."""
    if match.best_of:
        return match.best_of
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


MATCH_LENGTH_FIELDS = {"best_of", "best_of_by_stage"}


def freeze_started(event: Event) -> int:
    """Before an event's match lengths change part-way (a live event, user request 2026-11-28): every
    match already decided, on a table or being scored keeps the best of it is played over. Call with
    the event's current (old) rules, inside the transaction that changes them. Returns how many were
    frozen."""
    from scoring.models import Scorecard  # scoring builds on competitions

    scored = Scorecard.objects.filter(revision__gt=0).filter(
        Q(match_id=OuterRef("pk")) | Q(rubber__match_id=OuterRef("pk"))
    )
    started = (
        Match.objects.filter(draw__event=event, best_of__isnull=True)
        .exclude(draw__status=DrawVersion.Status.SUPERSEDED)
        .annotate(scored=Exists(scored))
        .filter(
            Q(status=Match.Status.COMPLETED)
            | Q(dispatched_at__isnull=False)
            | Q(scored=True)
            | Q(rubbers__status__in=[Rubber.Status.COMPLETED, Rubber.Status.NOT_PLAYED])
        )
        .distinct()
    )
    frozen = 0
    for match in started:
        match.best_of = best_of_for(match, event)
        match.save(update_fields=["best_of"])
        frozen += 1
    return frozen


def describe(event: Event) -> str:
    """ "best of 3, 5 from the quarter-finals, 7 in the final", for the match-day log."""
    rules = event.best_of_by_stage or {}
    words = {
        GROUP: "in the groups",
        EARLY: "in the knockout",
        QUARTER: "from the quarter-finals",
        SEMI: "from the semi-finals",
        FINAL: "in the final",
    }
    parts = [f"best of {event.best_of}"]
    if rules.get(GROUP, event.best_of) != event.best_of:
        parts.append(f"{rules[GROUP]} {words[GROUP]}")
    current = event.best_of
    for stage in KNOCKOUT_STAGES:
        if stage in rules and rules[stage] != current:
            parts.append(f"{rules[stage]} {words[stage]}")
            current = rules[stage]
    return ", ".join(parts)
