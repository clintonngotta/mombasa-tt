"""Incidents of a match (REQ-043, TASK-083), projected from the umpire's accepted events.

The engine decides what each event does; this records the incidents that still stand after undos, with
the card each offence earned, who it was for and the score when it happened, for the match page, the
live view and the referee. Penalty points are points like any other in the state: they are noted on the
card here, not counted twice.
"""

from .engine import LADDER_MAX, PLAYERS, SIDES, Scoring, offences_of
from .models import MatchIncident, Scorecard

Kind = MatchIncident.Kind
KINDS = {
    "timeout": Kind.TIMEOUT,
    "timeout_end": Kind.TIMEOUT_END,
    "card": Kind.CARD,
    "adviser_card": Kind.ADVISER_CARD,
    "suspension": Kind.SUSPENSION,
    "suspension_end": Kind.SUSPENSION_END,
    "expedite": Kind.EXPEDITE,
    "retire": Kind.RETIRED,
    "disqualify": Kind.DISQUALIFIED,
}
MAX_NOTE = 200
WITH_REASON = (Kind.CARD, Kind.ADVISER_CARD)  # the engine checks a reason on these alone


def user_at(players: dict[str, list], slot: str):
    """The user in a slot ("a2": the second player of side a), or None if the side has fewer."""
    people = players.get(slot[0], [])
    position = int(slot[1]) - 1
    return people[position] if position < len(people) else None


def standing(scorecard: Scorecard, config: dict) -> list[tuple]:
    """(event, its sequence, when it arrived, the state before it) for every event an undo hasn't
    taken back, in order."""
    scoring = Scoring(config)
    kept: list[tuple] = []
    for event in scorecard.events.order_by("sequence"):
        before = scoring.state
        scoring.push(event.payload)
        if event.payload.get("type") == "undo":
            kept.pop()
        elif scoring.state is not before:  # an event that changed nothing leaves nothing to undo
            kept.append((event.payload, event.sequence, event.received_at, before))
    return kept


def rebuild(scorecard: Scorecard, config: dict, players: dict[str, list]) -> None:
    """Write the sheet's incidents as they now stand. `players` are the users of each side in slot
    order, so a card for a2 is the second player of side a."""

    rows = []
    for event, sequence, at, before in standing(scorecard, config):
        kind = KINDS.get(event.get("type"))
        if kind is None:
            continue
        row = MatchIncident(
            scorecard=scorecard,
            sequence=sequence,
            kind=kind,
            game_number=before["game_number"],
            score=list(before["points"]),
            at=at,
            reason=event["reason"] if kind in WITH_REASON else "",
            note=(event.get("note") or "")[:MAX_NOTE] if isinstance(event.get("note"), str) else "",
        )
        if kind == Kind.CARD:
            player = event["player"]
            offence = offences_of(config, before, player) + 1
            row.side, row.player = player[0], user_at(players, player)
            row.card = MatchIncident.Card.YELLOW if offence == 1 else MatchIncident.Card.YELLOW_RED
            row.penalty_points = offence - 1
        elif kind == Kind.ADVISER_CARD:
            row.side = event["side"]
            warned = before["advisers"][SIDES.index(event["side"])]
            row.card = MatchIncident.Card.YELLOW if warned == 0 else MatchIncident.Card.RED
        elif "side" in event and event["side"] in SIDES:
            row.side = event["side"]
        rows.append(row)
    scorecard.incidents.all().delete()
    MatchIncident.objects.bulk_create(rows)


def carry_for(scorecard: Scorecard, players_of) -> dict | None:
    """What a tie's later rubber starts with (3.5.2.7): each player's offences in the tie's earlier
    rubbers, and each team's adviser cards. None when nothing carries. Each sheet already starts with
    what was carried into it, so a player's count is the largest any earlier sheet holds for them."""
    rubber = scorecard.rubber
    if rubber is None:
        return None
    earlier = Scorecard.objects.filter(rubber__match_id=rubber.match_id, rubber__position__lt=rubber.position)
    offences: dict = {}
    advisers = [0, 0]
    for sheet in earlier.select_related("rubber"):
        state = sheet.state or {}
        seats = players_of(sheet)
        for slot, count in (state.get("offences") or {}).items():
            user = user_at(seats, slot)
            if count and user is not None:
                offences[user.pk] = max(offences.get(user.pk, 0), count)
        for index, cards in enumerate(state.get("advisers") or [0, 0]):
            advisers[index] = max(advisers[index], cards)
    seats = players_of(scorecard)
    starting = {}
    for slot in PLAYERS:
        user = user_at(seats, slot)
        starting[slot] = min(LADDER_MAX, offences.get(user.pk, 0)) if user is not None else 0
    if not any(starting.values()) and not any(advisers):
        return None
    return {"offences": starting, "advisers": advisers}
