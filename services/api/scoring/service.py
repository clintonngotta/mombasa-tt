"""Umpire assignment, accepting score events and confirming a result (REQ-012).

The deck computes the score with the TypeScript reducer; nothing it says about the score is taken on
trust. Every event is replayed here through the Python engine, in order, and only a sheet whose replayed
state is a finished match can be confirmed. Confirmation writes the official result through the same
functions as every other result (`drawing.record_result`, `ties.record_rubber`).
"""

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from competitions import drawing, official, ties
from competitions.models import DrawVersion, Event, Match, Rubber, RubberPlayer, Tournament
from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.permissions import Permission
from realtime import broadcast

from .engine import Scoring, ScoringError, initial_state
from .models import ScoreAssignment, Scorecard, ScoreConflict, ScoreEvent, ScoringStatus

# Who may be given a match to score: people the club trusts with scoring, and those who run competitions.
UMPIRE_PERMISSIONS = {Permission.SCORING_ASSIGNED, Permission.COMPETITIONS_MANAGE, Permission.RESULTS_MANAGE}
MAX_BATCH = 200
MAX_CONFLICT_EVENTS = 500
# One person can't fill the organizers' page: this many reported events per sheet, then no more.
MAX_REPORTED_PER_SHEET = 2000
EVENT_TYPES = {"start", "point", "choose_server", "timeout", "undo"}


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
    config = {"best_of": event.best_of, "doubles": doubles}
    from . import incidents  # incidents builds on the models and the engine, as this does

    carry = incidents.carry_for(scorecard, players_of)
    if carry is not None:  # a tie's later rubber starts with the warnings and penalties of the earlier
        config["carry"] = carry
    return config


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
    mine = scorecard is not None and viewer.is_authenticated and is_umpire_of(scorecard, viewer)
    return {
        "scorecard_id": scorecard.id if mine else None,
        "status": status,
        "umpire_name": umpire.display_name if umpire else "",
        "can_score": mine and scorable and not scorecard.confirmed_at,
        "can_assign": staff and scorable,
        "incidents": incidents_of(scorecard) if scorecard else [],
    }


def incidents_of(scorecard: Scorecard, with_notes: bool = False) -> list[dict]:
    """The sheet's incidents as IncidentSerializer shows them; the umpire's notes on the sheet only."""
    rows = []
    for incident in scorecard.incidents.select_related("player"):
        row = {
            "sequence": incident.sequence,
            "kind": incident.kind,
            "side": incident.side,
            "player_name": incident.player.display_name if incident.player else "",
            "card": incident.card,
            "penalty_points": incident.penalty_points,
            "reason": incident.reason,
            "game_number": incident.game_number,
            "score": incident.score,
            "at": incident.at,
        }
        if with_notes:
            row["note"] = incident.note
        rows.append(row)
    return rows


def may_disqualify(scorecard: Scorecard, user) -> bool:
    return Permission.RESULTS_REFEREE in effective_permissions(
        user, event_of(scorecard).tournament.organization
    )


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
        from reservations import service as reservations  # it builds on scoring's sheets in turn

        reservations.ensure_umpire_free(match, umpire)
    scorecard.umpire = umpire
    scorecard.assignment_id = uuid.uuid4()
    scorecard.assigned_by = actor
    scorecard.assigned_at = timezone.now()
    # A new assignment starts without a device: whichever the umpire opens it on takes it.
    scorecard.device_id, scorecard.device_label, scorecard.device_since = None, "", None
    scorecard.save()
    kind = ScoreAssignment.Kind.ASSIGNED if umpire else ScoreAssignment.Kind.UNASSIGNED
    _log(scorecard, kind, actor)
    return scorecard


def _log(scorecard: Scorecard, kind: str, actor) -> None:
    ScoreAssignment.objects.create(
        scorecard=scorecard,
        kind=kind,
        umpire=scorecard.umpire,
        actor=actor,
        assignment_id=scorecard.assignment_id,
        device_id=scorecard.device_id,
        device_label=scorecard.device_label,
        revision=scorecard.revision,
    )


def take_device(scorecard: Scorecard, actor, device_id, label: str, take_over: bool) -> None:
    """The umpire's device takes the sheet. An unheld sheet is simply taken. A sheet held by another
    device is taken only when the umpire says so (`take_over`): that issues a new assignment id, so the
    other device can send nothing more, and what it hadn't sent becomes a conflict on that device.
    Call with the sheet locked."""
    if scorecard.confirmed_at:
        raise _conflict("already_confirmed", "This result is confirmed.")
    if scorecard.device_id == device_id:
        return
    if scorecard.device_id is None:
        kind = ScoreAssignment.Kind.DEVICE
    elif take_over:
        kind = ScoreAssignment.Kind.TAKE_OVER
        scorecard.assignment_id = uuid.uuid4()
    else:
        raise _conflict(
            "other_device",
            "This match is being scored on another device. Take it over here to carry on from this one.",
        )
    scorecard.device_id, scorecard.device_label, scorecard.device_since = (
        device_id,
        label[:80],
        timezone.now(),
    )
    scorecard.save(update_fields=["assignment_id", "device_id", "device_label", "device_since"])
    _log(scorecard, kind, actor)


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


def _ensure_in_play(scorecard: Scorecard, assignment_id, device_id=None) -> None:
    if scorecard.confirmed_at:
        raise _conflict(
            "already_confirmed", "This result is confirmed. A correction is made by the organizers."
        )
    if str(assignment_id) != str(scorecard.assignment_id):
        raise _conflict("stale_assignment", "This match was reassigned. Open it again to carry on.")
    # A sheet a device has taken is scored from that device only.
    if scorecard.device_id is not None and scorecard.device_id != device_id:
        raise _conflict("other_device", "This match is being scored on another device.")
    official.ensure_not_held(scorecard.tie_or_match)
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


def submit(scorecard: Scorecard, actor, assignment_id, events: list[dict], device_id=None) -> dict:
    """Accept score events in order. An event already accepted (same id and sequence) is skipped, so a
    retry is harmless. The first event that is out of sequence or that the rules refuse stops the
    batch: what came before it is kept, and the reply says what was refused and why. A sheet no device
    holds yet is taken by the device that sends its first events. Call with the sheet locked."""
    if scorecard.device_id is None and device_id is not None and not scorecard.confirmed_at:
        take_device(scorecard, actor, device_id, "", take_over=False)
    _ensure_in_play(scorecard, assignment_id, device_id)
    scoring = replayed(scorecard)
    known = dict(scorecard.events.values_list("id", "sequence"))
    accepted, refused = 0, None
    seen = scorecard.revision  # what the server held when the batch arrived
    for sent in events:
        if known.get(sent["id"]) == sent["sequence"]:
            continue  # a retry of something already accepted
        if sent["id"] in known or sent["sequence"] <= scorecard.revision:
            refused = {"sequence": sent["sequence"], "code": "sequence_conflict"}
            break
        if sent.get("expected_revision", 0) > seen:
            # The device built on events this server doesn't hold: never accept on top of a hole.
            refused = {"sequence": sent["sequence"], "code": "revision_conflict"}
            break
        if sent["sequence"] != scorecard.revision + 1:
            refused = {"sequence": sent["sequence"], "code": "sequence_gap"}
            break
        refusal = _refused_for(scorecard, actor, sent["event"])
        if refusal:
            refused = {"sequence": sent["sequence"], "code": refusal}
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
        from . import incidents

        incidents.rebuild(scorecard, config_of(scorecard), players_of(scorecard))
        event = event_of(scorecard)
        broadcast.tournament_changed(event.tournament_id, "scores", event_id=event.id)
    return {"accepted": accepted, "refused": refused}


def _refused_for(scorecard: Scorecard, actor, event) -> str | None:
    """What the server refuses beyond the rules: a note too long to keep, and a disqualification from
    anybody but the referee (decision D5)."""
    from . import incidents

    if not isinstance(event, dict):
        return None
    note = event.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > incidents.MAX_NOTE):
        return "invalid_note"
    if event.get("type") == "disqualify" and not may_disqualify(scorecard, actor):
        return "referee_only"
    return None


def confirm(scorecard: Scorecard, actor, assignment_id, revision: int, device_id=None) -> None:
    """The umpire confirms the result, from the device that holds the current assignment. Refused
    unless the events accepted so far, replayed here, are a finished match: an early finish is not a
    result. Confirming again what is already confirmed (a retry whose first answer was lost) changes
    nothing and succeeds. Call with the tournament row and the sheet locked."""
    same_sheet = str(assignment_id) == str(scorecard.assignment_id) and revision == scorecard.revision
    if scorecard.confirmed_at and same_sheet:
        return
    _ensure_in_play(scorecard, assignment_id, device_id)
    if revision != scorecard.revision:
        raise _conflict("stale_revision", "Not every point has reached the server yet. Wait for it to save.")
    state = replayed(scorecard).state
    if state["status"] != "completed":
        raise _conflict("match_not_finished", "The match isn't finished, so there is no result to confirm.")
    match = scorecard.tie_or_match
    winner = match.entry_a if state["winner"] == "a" else match.entry_b
    # A retirement or disqualification keeps the points played, the unfinished game included; nothing
    # is made up (REQ-043).
    outcome = state.get("outcome") or Match.Outcome.PLAYED
    games = [list(game) for game in state["games"]]
    if outcome != Match.Outcome.PLAYED and sum(state["points"]):
        games.append(list(state["points"]))
    if scorecard.rubber_id:
        ties.record_rubber(scorecard.rubber, winner, outcome=outcome, games=games, actor=actor)
    else:
        drawing.record_result(match, winner, outcome=outcome, games=games, actor=actor)
    scorecard.state = state
    scorecard.confirmed_at = timezone.now()
    scorecard.confirmed_by = actor
    scorecard.save(update_fields=["state", "confirmed_at", "confirmed_by"])
    event = event_of(scorecard)
    broadcast.tournament_changed(event.tournament_id, "results", event_id=event.id)


def _who(user_id) -> str | None:
    return str(user_id) if user_id else None


def strike_out(match: Match, actor=None) -> list[dict]:
    """Empty the match's score sheet because the match is to be played again with another entry
    (REQ-015). What was scored is returned, to be kept with the decision; the sheet itself starts
    over under a new assignment id, so a device still holding the old one is cut off."""
    kept = []
    for scorecard in Scorecard.objects.select_for_update().filter(match=match):
        if scorecard.revision == 0 and scorecard.confirmed_at is None:
            continue
        kept.append(
            {
                "scorecard_id": str(scorecard.id),
                "revision": scorecard.revision,
                "state": scorecard.state,
                "confirmed_at": scorecard.confirmed_at.isoformat() if scorecard.confirmed_at else None,
                "confirmed_by": _who(scorecard.confirmed_by_id),
                "umpire": _who(scorecard.umpire_id),
                "events": [
                    {
                        "id": str(event.id),
                        "sequence": event.sequence,
                        "event": event.payload,
                        "actor": _who(event.actor_id),
                        "device_time": event.device_time.isoformat() if event.device_time else None,
                        "received_at": event.received_at.isoformat(),
                    }
                    for event in scorecard.events.all()
                ],
            }
        )
        _log(scorecard, ScoreAssignment.Kind.RESET, actor)  # who held it and how far it had got
        scorecard.events.all().delete()
        scorecard.revision = 0
        scorecard.state = initial_state(config_of(scorecard))
        scorecard.incidents.all().delete()
        scorecard.confirmed_at = scorecard.confirmed_by = None
        scorecard.assignment_id = uuid.uuid4()
        scorecard.device_id, scorecard.device_label, scorecard.device_since = None, "", None
        scorecard.save()
    return kept


def sheet_context(scorecard: Scorecard) -> dict:
    """Which match a sheet is for, as SheetContextSerializer shows it."""
    match = scorecard.tie_or_match
    sides = players_of(scorecard)

    def title(side: str, entry) -> str:
        names = " / ".join(user.display_name for user in sides[side])
        return f"{names} ({entry.team_name})" if scorecard.rubber_id else names

    return {
        "scorecard_id": scorecard.id,
        "event_id": match.draw.event_id,
        "event_name": match.draw.event.name,
        "match_id": match.id,
        "label": label_of(scorecard),
        "a": title("a", match.entry_a),
        "b": title("b", match.entry_b),
    }


def overview(tournament: Tournament) -> dict:
    """The tournament's open sheets and conflict reports, as ScoringOverviewSerializer shows them."""
    published = DrawVersion.Status.PUBLISHED
    # Sheets of every draw: a report about a match of a draw since replaced must still be seen.
    cards = (
        Scorecard.objects.filter(
            Q(match__draw__event__tournament=tournament)
            | Q(rubber__match__draw__event__tournament=tournament)
        )
        # Only what the page shows: sheets under way or waiting, and sheets somebody reported about.
        .filter(Q(confirmed_at__isnull=True, revision__gt=0) | Q(conflicts__isnull=False))
        .distinct()
        .select_related(
            "umpire",
            "match__draw__event",
            "rubber__match__draw",
            "match__draw",
            "match__entry_a",
            "match__entry_b",
            "rubber__match__draw__event",
            "rubber__match__entry_a",
            "rubber__match__entry_b",
        )
        .prefetch_related("assignments__umpire", "assignments__actor", "conflicts__reported_by", "events")
    )

    def name(user) -> str:
        return user.display_name if user else ""

    sheets, conflicts = [], []
    for card in cards:
        context = None
        if not card.confirmed_at and card.revision > 0 and card.tie_or_match.draw.status == published:
            context = sheet_context(card)
            events = list(card.events.all())
            sheets.append(
                {
                    "sheet": context,
                    "status": card.shown_status,
                    "umpire": name(card.umpire),
                    "device_label": card.device_label,
                    "revision": card.revision,
                    "last_event_at": events[-1].received_at if events else None,
                    "games": card.state["games"],
                    "points": card.state["points"],
                    "history": [
                        {
                            "kind": step.kind,
                            "umpire": name(step.umpire),
                            "actor": name(step.actor),
                            "device_label": step.device_label,
                            "revision": step.revision,
                            "created_at": step.created_at,
                        }
                        for step in card.assignments.all()
                    ],
                }
            )
        reports = list(card.conflicts.all())
        if not reports:
            continue
        context = context or sheet_context(card)
        official = {kept.sequence: kept.payload for kept in card.events.all()}
        for report in reports:
            places = [sent["sequence"] for sent in report.events]
            conflicts.append(
                {
                    "id": report.id,
                    "sheet": context,
                    "reported_by": name(report.reported_by),
                    "device_label": report.device_label,
                    "created_at": report.created_at,
                    "events": [
                        {"sequence": sent["sequence"], "event": sent["event"]} for sent in report.events
                    ],
                    "accepted": [
                        {"sequence": place, "event": official[place]} for place in places if place in official
                    ],
                    "resolved_at": report.resolved_at,
                    "resolved_by": name(report.resolved_by),
                    "resolution": report.resolution,
                }
            )
    sheets.sort(
        key=lambda row: (
            row["status"] != ScoringStatus.FINISHED,
            row["sheet"]["event_name"],
            row["sheet"]["label"],
        )
    )
    conflicts.sort(key=lambda row: (row["resolved_at"] is not None, row["created_at"]))
    return {"sheets": sheets, "conflicts": conflicts}


def may_report(scorecard: Scorecard, user) -> bool:
    """Whoever holds the sheet, or held it once, may say what their device still has."""
    return scorecard.umpire_id == user.id or scorecard.assignments.filter(umpire=user).exists()


def report_conflict(scorecard: Scorecard, user, report: dict) -> ScoreConflict:
    """Keep what a device wrote and the server didn't take. Nothing about the score changes. Sending
    the same report again (same id) returns the one already kept."""
    events = [
        {
            "id": str(sent["id"]),
            "sequence": sent["sequence"],
            "event": sent["event"],
            "device_time": sent["device_time"].isoformat() if sent.get("device_time") else None,
        }
        for sent in report["events"]
    ]
    known = ScoreConflict.objects.select_for_update().filter(pk=report["id"]).first()
    if known is not None and (known.scorecard_id != scorecard.id or known.reported_by_id != user.id):
        raise _conflict("conflict_exists", "That report belongs to somebody else.")
    already = {sent["id"] for sent in known.events} if known else set()
    fresh = [sent for sent in events if sent["id"] not in already]
    held = sum(len(kept.events) for kept in scorecard.conflicts.filter(reported_by=user))
    if held + len(fresh) > MAX_REPORTED_PER_SHEET:
        raise _conflict(
            "too_many_reports", "Too much has been reported for this match. Talk to the organizers."
        )
    if known is not None:
        # The same report again, perhaps with more in it than the first time got through: what is new
        # is added, so nothing a device holds can go missing behind an id the server already knows.
        if fresh:
            known.events = [*known.events, *fresh]
            known.resolved_at, known.resolved_by, known.resolution = None, None, ""
            known.save(update_fields=["events", "resolved_at", "resolved_by", "resolution"])
        return known
    return ScoreConflict.objects.create(
        id=report["id"],
        scorecard=scorecard,
        reported_by=user,
        assignment_id=report.get("assignment_id"),
        device_id=report.get("device_id"),
        device_label=report.get("device_label", "")[:80],
        events=events,
        revision=scorecard.revision,
    )


def resolve_conflict(conflict: ScoreConflict, actor, note: str) -> None:
    """Staff have looked at it and say what was done. The record stays."""
    if conflict.resolved_at:
        raise _conflict("already_resolved", "This has already been dealt with.")
    conflict.resolved_at = timezone.now()
    conflict.resolved_by = actor
    conflict.resolution = note
    conflict.save(update_fields=["resolved_at", "resolved_by", "resolution"])
