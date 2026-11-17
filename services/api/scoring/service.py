"""Umpire assignment, accepting score events and confirming a result (REQ-012).

The deck computes the score with the TypeScript reducer; nothing it says about the score is taken on
trust. Every event is replayed here through the Python engine, in order, and only a sheet whose replayed
state is a finished match can be confirmed. Confirmation writes the official result through the same
functions as every other result (`drawing.record_result`, `ties.record_rubber`).
"""

import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from competitions import drawing, ties
from competitions.models import DrawVersion, Event, Match, Rubber, RubberPlayer, Tournament
from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.permissions import Permission

from .engine import Scoring, ScoringError
from .models import Scorecard, ScoreEvent, ScoringStatus

# Who may be given a match to score: people the club trusts with scoring, and those who run competitions.
UMPIRE_PERMISSIONS = {Permission.SCORING_ASSIGNED, Permission.COMPETITIONS_MANAGE, Permission.RESULTS_MANAGE}
MAX_BATCH = 200


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def event_of(scorecard: Scorecard) -> Event:
    return scorecard.tie_or_match.draw.event


def config_of(scorecard: Scorecard) -> dict:
    event = event_of(scorecard)
    doubles = (
        scorecard.rubber.kind == Rubber.Kind.DOUBLES
        if scorecard.rubber_id
        else event.kind == Event.Kind.DOUBLES
    )
    return {"best_of": event.best_of, "doubles": doubles}


def players_of(scorecard: Scorecard) -> dict[str, list]:
    """The users on side a and side b, in slot order (a1, a2 / b1, b2)."""
    if scorecard.rubber_id:
        placed = list(scorecard.rubber.players.select_related("user"))
        return {
            "a": [p.user for p in placed if p.side == RubberPlayer.Side.A],
            "b": [p.user for p in placed if p.side == RubberPlayer.Side.B],
        }
    match = scorecard.match
    return {
        "a": [place.user for place in match.entry_a.players.select_related("user")],
        "b": [place.user for place in match.entry_b.players.select_related("user")],
    }


def label_of(scorecard: Scorecard) -> str:
    """ "Semi-final", "Group B · Round 2", "Round 1 · Rubber 3"."""
    match = scorecard.tie_or_match
    shown = drawing.describe_match(match.draw, match.id)
    parts = [shown["group_name"], shown["round_name"]]
    if scorecard.rubber_id:
        parts.append(f"Rubber {scorecard.rubber.position}")
    return " · ".join(part for part in parts if part)


def summary(match: Match, rubber: Rubber | None, viewer, staff: bool) -> dict:
    """Where scoring stands for a match or rubber, as ScoringSummarySerializer shows it to `viewer`."""
    target = {"rubber": rubber} if rubber else {"match": match}
    scorecard = Scorecard.objects.select_related("umpire").filter(**target).first()
    try:
        ensure_scorable(match, rubber)
        scorable = True
    except ApiException:
        scorable = False
    umpire = scorecard.umpire if scorecard else None
    status = ScoringStatus.UNASSIGNED
    if scorecard and (umpire or scorecard.revision or scorecard.confirmed_at):
        status = scorecard.shown_status
    mine = scorecard is not None and is_umpire_of(scorecard, viewer)
    return {
        "scorecard_id": scorecard.id if mine else None,
        "status": status,
        "umpire_name": umpire.display_name if umpire else "",
        "can_score": mine and scorable and not scorecard.confirmed_at,
        "can_assign": staff and scorable,
    }


def ensure_scorable(match: Match, rubber: Rubber | None) -> None:
    """What can be given an umpire: an undecided individual match of the published draw whose two sides
    are known. In a team event that is a rubber, once both lineups are in."""
    event = match.draw.event
    if match.draw.status != DrawVersion.Status.PUBLISHED:
        raise _conflict("draw_not_published", "Only matches of the published draw are played.")
    if event.is_closed or event.tournament.is_closed:
        raise _conflict("event_closed", "This event is over.")
    if match.status != Match.Status.SCHEDULED:
        raise _conflict("match_decided", "This match is already decided.")
    if match.entry_a_id is None or match.entry_b_id is None:
        raise _conflict("match_not_ready", "Both sides of this match aren't known yet.")
    if event.is_team:
        if rubber is None:
            raise _conflict("score_rubbers", "A tie is scored rubber by rubber. Choose the rubber.")
        if rubber.status != Rubber.Status.SCHEDULED:
            raise _conflict("rubber_closed", "This rubber is already decided or was not needed.")
    elif rubber is not None:
        raise _conflict("not_a_tie", "Only matches of a team event have rubbers.")


def can_umpire(user, event: Event) -> bool:
    return bool(effective_permissions(user, event.tournament.organization) & UMPIRE_PERMISSIONS)


def assign(match: Match, rubber: Rubber | None, umpire, actor) -> Scorecard:
    """Give the match (or rubber) to an umpire, or take it back with `umpire=None`. Either way the
    assignment id changes, so a device still holding the old one can no longer send events. What was
    already scored stays. Call with the tournament row locked."""
    ensure_scorable(match, rubber)
    target = {"rubber": rubber} if rubber else {"match": match}
    scorecard = Scorecard.objects.select_for_update().filter(**target).first() or Scorecard(**target)
    if umpire is not None:
        if not can_umpire(umpire, match.draw.event):
            raise _conflict(
                "not_an_umpire",
                "Only members whose role lets them score matches, or who run competitions, can umpire.",
            )
        playing = [user.id for users in players_of(scorecard).values() for user in users]
        if umpire.id in playing:
            raise _conflict("umpire_plays", "A player can't umpire their own match.")
    scorecard.umpire = umpire
    scorecard.assignment_id = uuid.uuid4()
    scorecard.assigned_by = actor
    scorecard.assigned_at = timezone.now()
    scorecard.save()
    return scorecard


def is_umpire_of(scorecard: Scorecard, user) -> bool:
    """The user is assigned to the sheet and still holds a role that lets them score here. Losing the
    role or the membership takes the sheet away at once, not at the next assignment."""
    return scorecard.umpire_id == user.id and can_umpire(user, event_of(scorecard))


def locked(scorecard_id, user) -> Scorecard:
    """The sheet, locked for a change by the umpire assigned to it. For anybody else it doesn't exist."""
    scorecard = (
        Scorecard.objects.select_for_update(of=("self",))
        .select_related(
            "match__draw__event__tournament__organization",
            "rubber__match__draw__event__tournament__organization",
        )
        .filter(pk=scorecard_id, umpire=user)
        .first()
    )
    if scorecard is None or not is_umpire_of(scorecard, user):
        raise ApiException("not_found", "Not found.", 404)
    return scorecard


def _ensure_in_play(scorecard: Scorecard, assignment_id) -> None:
    if scorecard.confirmed_at:
        raise _conflict(
            "already_confirmed", "This result is confirmed. A correction is made by the organizers."
        )
    if str(assignment_id) != str(scorecard.assignment_id):
        raise _conflict("stale_assignment", "This match was reassigned. Open it again to carry on.")
    event = event_of(scorecard)
    if event.tournament.status != Tournament.Status.IN_PROGRESS or event.status != Event.Status.IN_PROGRESS:
        raise _conflict(
            "not_in_play", "The organizers haven't started this event, so it can't be scored yet."
        )
    ensure_scorable(scorecard.tie_or_match, scorecard.rubber)
    if scorecard.rubber_id:
        current = (
            scorecard.rubber.match.rubbers.filter(status=Rubber.Status.SCHEDULED).order_by("position").first()
        )
        if current is None or current.id != scorecard.rubber_id:
            raise _conflict("rubber_out_of_turn", "An earlier rubber of this tie is played first.")


def replayed(scorecard: Scorecard) -> Scoring:
    """The engine brought to where the accepted events leave it."""
    scoring = Scoring(config_of(scorecard))
    for payload in scorecard.events.values_list("payload", flat=True):
        scoring.push(payload)
    return scoring


def submit(scorecard: Scorecard, actor, assignment_id, events: list[dict]) -> dict:
    """Accept score events in order. An event already accepted (same id and sequence) is skipped, so a
    retry is harmless. The first event that is out of sequence or that the rules refuse stops the
    batch: what came before it is kept, and the reply says what was refused and why. Call with the
    sheet locked."""
    _ensure_in_play(scorecard, assignment_id)
    scoring = replayed(scorecard)
    known = dict(scorecard.events.values_list("id", "sequence"))
    accepted, refused = 0, None
    for sent in events:
        if known.get(sent["id"]) == sent["sequence"]:
            continue  # a retry of something already accepted
        if sent["id"] in known or sent["sequence"] <= scorecard.revision:
            refused = {"sequence": sent["sequence"], "code": "sequence_conflict"}
            break
        if sent["sequence"] != scorecard.revision + 1:
            refused = {"sequence": sent["sequence"], "code": "sequence_gap"}
            break
        try:
            scoring.push(sent["event"])
        except ScoringError as error:
            refused = {"sequence": sent["sequence"], "code": error.code}
            break
        try:
            with transaction.atomic():
                ScoreEvent.objects.create(
                    id=sent["id"],
                    scorecard=scorecard,
                    sequence=sent["sequence"],
                    payload=sent["event"],
                    device_time=sent.get("device_time"),
                    actor=actor,
                )
        except IntegrityError:  # the id belongs to an event of another sheet
            refused = {"sequence": sent["sequence"], "code": "sequence_conflict"}
            break
        known[sent["id"]] = sent["sequence"]
        scorecard.revision = sent["sequence"]
        accepted += 1
    if accepted:
        scorecard.state = scoring.state if refused is None else replayed(scorecard).state
        scorecard.save(update_fields=["revision", "state"])
    return {"accepted": accepted, "refused": refused}


def confirm(scorecard: Scorecard, actor, assignment_id, revision: int) -> None:
    """The umpire confirms the result, from the device that holds the current assignment. Refused
    unless the events accepted so far, replayed here, are a finished match: an early finish is not a
    result. Call with the tournament row and the sheet locked."""
    _ensure_in_play(scorecard, assignment_id)
    if revision != scorecard.revision:
        raise _conflict("stale_revision", "Not every point has reached the server yet. Wait for it to save.")
    state = replayed(scorecard).state
    if state["status"] != "completed":
        raise _conflict("match_not_finished", "The match isn't finished, so there is no result to confirm.")
    match = scorecard.tie_or_match
    winner = match.entry_a if state["winner"] == "a" else match.entry_b
    if scorecard.rubber_id:
        ties.record_rubber(scorecard.rubber, winner, games=state["games"])
    else:
        drawing.record_result(match, winner, games=state["games"])
    scorecard.state = state
    scorecard.confirmed_at = timezone.now()
    scorecard.confirmed_by = actor
    scorecard.save(update_fields=["state", "confirmed_at", "confirmed_by"])
