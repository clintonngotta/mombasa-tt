"""Who umpires each match still to be played, for the tournament's staff (TASK-153).

The umpires see their own matches on their page (TASK-151); staff see every match at once: those an
umpire has, and those still waiting for one. A tie is umpired rubber by rubber, so each of its rubbers
still to be played is a row of its own once the lineups are in; before then the tie has nothing to give.
"""

from django.db.models import Max, Q

from competitions.models import DrawVersion, Event, Match, Rubber, Tournament
from scoring.models import Scorecard, ScoringStatus

from . import board, service

ASSIGNED, UNASSIGNED = "assigned", "unassigned"


def _matches(tournament: Tournament):
    return (
        Match.objects.filter(
            draw__event__tournament=tournament,
            draw__status=DrawVersion.Status.PUBLISHED,
            draw__event__status__in=[Event.Status.SCHEDULED, Event.Status.IN_PROGRESS],
            status=Match.Status.SCHEDULED,
            entry_a__isnull=False,
            entry_b__isnull=False,
        )
        .select_related("draw__event", "entry_a", "entry_b", "table", "held_table", "planned_table")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
    )


def rows(tournament: Tournament) -> list[dict]:
    """Every match and rubber still to be played that can be given an umpire, soonest first, with its
    umpire if it has one. A handful of queries whatever the number of matches."""
    matches = list(_matches(tournament))
    team = [match.id for match in matches if match.draw.event.is_team]
    rubbers: dict = {}
    for rubber in Rubber.objects.filter(match_id__in=team, status=Rubber.Status.SCHEDULED).order_by(
        "position"
    ):
        rubbers.setdefault(rubber.match_id, []).append(rubber)
    cards = {
        card.rubber_id or card.match_id: card
        for card in Scorecard.objects.filter(
            Q(match_id__in=[match.id for match in matches]) | Q(rubber__match_id__in=team)
        ).select_related("umpire")
    }
    knockout = Q(stage=Match.Stage.KNOCKOUT)
    shape = {
        found["draw_id"]: (found["rounds"], found["groups"])
        for found in Match.objects.filter(draw_id__in={match.draw_id for match in matches})
        .values("draw_id")
        .annotate(rounds=Max("round", filter=knockout), groups=Max("group"))
    }
    found = []
    for match in matches:
        units = rubbers.get(match.id, []) if match.draw.event.is_team else [None]
        for rubber in units:
            card = cards.get(rubber.id if rubber else match.id)
            umpire = card.umpire if card else None
            status = card.shown_status if umpire else ScoringStatus.UNASSIGNED
            label = board._label(match, shape)
            found.append(
                {
                    "match_id": match.id,
                    "rubber_id": rubber.id if rubber else None,
                    "rubber_position": rubber.position if rubber else None,
                    "event_id": match.draw.event_id,
                    "event_name": match.draw.event.name,
                    "label": f"{label} · Rubber {rubber.position}" if rubber else label,
                    "a": service.entry_title(match.entry_a),
                    "b": service.entry_title(match.entry_b),
                    "scheduled_at": match.scheduled_at,
                    "table": match.table.label if match.table and match.dispatched_at else "",
                    "held_table": match.held_table.label if match.held_table else "",
                    "planned_table": match.planned_table.label if match.planned_table else "",
                    "umpire_id": umpire.id if umpire else None,
                    "umpire_name": umpire.display_name if umpire else "",
                    "status": status,
                }
            )
    found.sort(
        key=lambda row: (
            row["scheduled_at"] is None,
            row["scheduled_at"] or 0,
            row["event_name"],
            row["label"],
            row["rubber_position"] or 0,
        )
    )
    return found


def filtered(found: list[dict], which: str) -> list[dict]:
    if which == ASSIGNED:
        return [row for row in found if row["umpire_id"] is not None]
    if which == UNASSIGNED:
        return [row for row in found if row["umpire_id"] is None]
    return found


def totals(found: list[dict]) -> dict:
    assigned = sum(1 for row in found if row["umpire_id"] is not None)
    return {"assigned": assigned, "unassigned": len(found) - assigned}
