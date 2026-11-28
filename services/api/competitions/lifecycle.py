"""State changes of tournaments and events (REQ-007).

Tournament: draft -> published -> in progress -> completed, or cancelled from published or in progress.
Event: scheduled -> in progress -> completed, or cancelled. Every change is written to the lifecycle log
with the actor, the reason where one is needed, and the configuration as it stood.

Callers hold a row lock on the tournament (`select_for_update`), so two changes never interleave.
"""

import json

from django.utils import timezone
from rest_framework.renderers import JSONRenderer

from core.exceptions import ApiException
from core.permissions import is_platform_super_admin
from organizations.access import membership_permissions, official_for
from organizations.models import Membership
from organizations.permissions import Permission

from . import signals
from .models import Event, LifecycleEntry, Tournament
from .serializers import EventSerializer, TournamentSerializer

T = Tournament.Status
E = Event.Status
A = LifecycleEntry.Action


def _plain(data) -> dict:
    return json.loads(JSONRenderer().render(data))


def record(tournament: Tournament, action: str, actor, *, event: Event | None = None, reason: str = ""):
    LifecycleEntry.objects.create(
        tournament=tournament,
        event=event,
        event_name=event.name if event else "",
        action=action,
        actor=actor,
        reason=reason,
        snapshot=_plain(
            EventSerializer(event).data
            if event
            else TournamentSerializer(Tournament.objects.detailed().get(pk=tournament.pk)).data
        ),
    )


def _require(subject: Tournament | Event, *allowed: str, doing: str) -> None:
    if subject.status not in allowed:
        noun = "A tournament" if isinstance(subject, Tournament) else "An event"
        raise ApiException(
            "invalid_transition",
            f"{noun} that is {subject.get_status_display().lower()} can't be {doing}.",
            409,
        )


def _move(subject, status: str, stamp: str, **fields) -> None:
    subject.status = status
    setattr(subject, stamp, timezone.now())
    for name, value in fields.items():
        setattr(subject, name, value)
    subject.save(update_fields=["status", stamp, *fields])


def _ready_to_publish(tournament: Tournament) -> None:
    _require(tournament, T.DRAFT, doing="published")
    missing = []
    if tournament.venue_id is None:
        missing.append("a venue")
    if not tournament.events.exists():
        missing.append("at least one event")
    if missing:
        raise ApiException("not_ready", f"Add {' and '.join(missing)} before publishing.", 409)


def can_approve(tournament: Tournament, actor) -> bool:
    if is_platform_super_admin(actor):
        return True
    if tournament.scope == Tournament.Scope.INTERNATIONAL:
        return False
    return official_for(
        actor, tournament.organization, country_only=tournament.scope == Tournament.Scope.NATIONAL
    )


def ensure_may_change_scope(tournament: Tournament, actor) -> None:
    """The host club chooses its tournament's tier. An official from outside the club can change it only
    when they could approve the tier it has now, so nobody can move a tournament down into a tier they
    approve themselves."""
    if is_platform_super_admin(actor):
        return
    host = (
        Membership.objects.active()
        .filter(organization=tournament.organization, user=actor)
        .select_related("organization")
        .prefetch_related("roles", "organization__roles")
        .first()
    )
    if host and Permission.COMPETITIONS_MANAGE in membership_permissions(host):
        return
    if tournament.scope != Tournament.Scope.LOCAL and not can_approve(tournament, actor):
        raise ApiException(
            "permission_denied",
            "Only the host club or an official who approves its current tier can change the scope.",
            403,
        )


def request_approval(tournament: Tournament, actor) -> None:
    _ready_to_publish(tournament)
    if (
        tournament.scope == Tournament.Scope.LOCAL
        or tournament.approval_status == Tournament.Approval.PENDING
    ):
        raise ApiException("invalid_transition", "This tournament cannot request approval now.", 409)
    tournament.approval_status = Tournament.Approval.PENDING
    tournament.save(update_fields=["approval_status"])
    record(tournament, A.APPROVAL_REQUESTED, actor)


def reset_pending_approval(tournament: Tournament) -> None:
    if tournament.approval_status == Tournament.Approval.PENDING:
        tournament.approval_status = Tournament.Approval.NOT_REQUESTED
        tournament.save(update_fields=["approval_status"])


def reject_approval(tournament: Tournament, actor, reason: str) -> None:
    if not can_approve(tournament, actor):
        raise ApiException("permission_denied", "Only the official for this tournament can decide.", 403)
    _require(tournament, T.DRAFT, doing="reviewed")
    if tournament.approval_status != Tournament.Approval.PENDING:
        raise ApiException("invalid_transition", "There is no pending approval to decline.", 409)
    tournament.approval_status = Tournament.Approval.REJECTED
    tournament.save(update_fields=["approval_status"])
    record(tournament, A.APPROVAL_REJECTED, actor, reason=reason)


def publish(tournament: Tournament, actor) -> None:
    _ready_to_publish(tournament)
    if tournament.scope == Tournament.Scope.LOCAL:
        _move(tournament, T.PUBLISHED, "published_at")
    else:
        if not can_approve(tournament, actor):
            raise ApiException(
                "permission_denied", "This tournament needs approval from the responsible official.", 403
            )
        if tournament.approval_status != Tournament.Approval.PENDING and not is_platform_super_admin(actor):
            raise ApiException("approval_not_requested", "Request approval before publishing.", 409)
        _move(tournament, T.PUBLISHED, "published_at", approval_status=Tournament.Approval.APPROVED)
    record(tournament, A.PUBLISHED, actor)


def start(tournament: Tournament, actor) -> None:
    _require(tournament, T.PUBLISHED, doing="started")
    if not tournament.events.exclude(status=E.CANCELLED).exists():
        raise ApiException("not_ready", "Every event is cancelled, so there is nothing to start.", 409)
    _move(tournament, T.IN_PROGRESS, "started_at")
    record(tournament, A.STARTED, actor)


def complete(tournament: Tournament, actor) -> None:
    _require(tournament, T.IN_PROGRESS, doing="completed")
    if tournament.events.exclude(status__in=[E.COMPLETED, E.CANCELLED]).exists():
        raise ApiException(
            "events_unfinished", "Complete or cancel every event before completing the tournament.", 409
        )
    _move(tournament, T.COMPLETED, "completed_at")
    record(tournament, A.COMPLETED, actor)


def cancel(tournament: Tournament, actor, reason: str) -> None:
    """Terminal. Events that haven't finished are cancelled with it; completed ones keep their result."""
    _require(tournament, T.PUBLISHED, T.IN_PROGRESS, doing="cancelled")
    for event in tournament.events.exclude(status__in=[E.COMPLETED, E.CANCELLED]):
        _move(event, E.CANCELLED, "cancelled_at", cancel_reason=reason)
        signals.event_closed.send(sender=Event, event=event, actor=actor)
    _move(tournament, T.CANCELLED, "cancelled_at", cancel_reason=reason)
    record(tournament, A.CANCELLED, actor, reason=reason)


def start_event(tournament: Tournament, event: Event, actor) -> None:
    """From here the event's structure (Event.STRUCTURE_FIELDS) is frozen."""
    _require(event, E.SCHEDULED, doing="started")
    if tournament.status != T.IN_PROGRESS:
        raise ApiException("tournament_not_started", "Start the tournament before starting its events.", 409)
    _move(event, E.IN_PROGRESS, "started_at")
    record(tournament, A.EVENT_STARTED, actor, event=event)


def complete_event(tournament: Tournament, event: Event, actor) -> None:
    _require(event, E.IN_PROGRESS, doing="completed")
    if event.paused_at is not None:
        raise ApiException(
            "event_paused",
            "A corrected result left a later match to decide. Settle it before completing the event.",
            409,
        )
    left = event.count_matches_left()
    if left:
        raise ApiException(
            "matches_left",
            f"{left} {'match has' if left == 1 else 'matches have'} no result yet. Record every result "
            "before completing the event.",
            409,
        )
    _move(event, E.COMPLETED, "completed_at")
    signals.event_closed.send(sender=Event, event=event, actor=actor)
    record(tournament, A.EVENT_COMPLETED, actor, event=event)


def reopen_event(tournament: Tournament, event: Event, actor, reason: str) -> None:
    """Undo a completion made too early: the event is in progress again, so results can be recorded and
    corrected. Only a platform super admin may, while the tournament itself is still running."""
    if not is_platform_super_admin(actor):
        raise ApiException("permission_denied", "Only a platform super admin can reopen an event.", 403)
    _require(event, E.COMPLETED, doing="reopened")
    if tournament.status != T.IN_PROGRESS:
        raise ApiException(
            "tournament_not_running",
            f"This tournament is {tournament.get_status_display().lower()}, so its events can't be reopened.",
            409,
        )
    event.status = E.IN_PROGRESS
    event.completed_at = None
    event.save(update_fields=["status", "completed_at"])
    record(tournament, A.EVENT_REOPENED, actor, event=event, reason=reason)


def cancel_event(tournament: Tournament, event: Event, actor, reason: str) -> None:
    _require(event, E.SCHEDULED, E.IN_PROGRESS, doing="cancelled")
    if tournament.status == T.DRAFT:
        raise ApiException("not_published", "Nobody has seen this event yet. Delete it instead.", 409)
    _move(event, E.CANCELLED, "cancelled_at", cancel_reason=reason)
    signals.event_closed.send(sender=Event, event=event, actor=actor)
    record(tournament, A.EVENT_CANCELLED, actor, event=event, reason=reason)
