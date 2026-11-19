"""Publishing the day schedule (TASK-081, REQ-043).

Publishing copies the organizers' working plan into what everybody sees and records it as the next
numbered version, with what changed from the one before. A delay (a table starting late or out of
service) moves the rest of that table's published matches on, and everything that then clashes with
them, and is published as a version of its own.

A change is news for a match's players and umpire when the match had a published start and now has
another table, no start, or a start more than the tournament's notice threshold away. They hear by
email from the outbox worker, one message each with all their moved matches; nobody else is told.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from core.exceptions import ApiException
from outbox import service as outbox

from . import scheduling
from .models import Match, ScheduleVersion, Tournament

logger = logging.getLogger(__name__)

NOTIFY = "schedule.notify"


def _iso(moment) -> str | None:
    return moment.isoformat() if moment else None


def _table(table) -> dict | None:
    return {"id": str(table.id), "label": table.label} if table else None


def _slot(match: Match) -> dict:
    return {
        "match_id": str(match.id),
        "label": scheduling.label(match),
        "title": scheduling._title(match),
        "table": _table(match.planned_table),
        "scheduled_at": _iso(match.scheduled_at),
    }


def is_news(tournament: Tournament, before: tuple, after: tuple) -> bool:
    """Whether moving a match from `before` to `after` (table, start) is worth telling its people."""
    (old_table, old_at), (new_table, new_at) = before, after
    if old_at is None:
        return False  # it had no published time: nothing anybody was relying on
    if new_at is None or (old_table is not None and getattr(new_table, "id", None) != old_table.id):
        return True
    return abs(new_at - old_at) > timedelta(minutes=tournament.schedule_notice_minutes)


def _record(tournament, actor, kind, moves: list, **extra) -> ScheduleVersion:
    """Apply `moves` (match, new table, new start) to what is published, and keep the version."""
    changes = []
    for match, table, at in moves:
        before = (match.planned_table, match.scheduled_at)
        if (getattr(table, "id", None), at) == (match.planned_table_id, match.scheduled_at):
            continue
        changes.append(
            {
                "match_id": str(match.id),
                "label": scheduling.label(match),
                "title": scheduling._title(match),
                "before": {"table": _table(before[0]), "scheduled_at": _iso(before[1])},
                "after": {"table": _table(table), "scheduled_at": _iso(at)},
                "notify": is_news(tournament, before, (table, at)),
            }
        )
        match.planned_table, match.scheduled_at = table, at
        match.save(update_fields=["planned_table", "scheduled_at"])
    last = tournament.schedule_versions.order_by("-number").values_list("number", flat=True).first()
    version = ScheduleVersion.objects.create(
        tournament=tournament,
        number=(last or 0) + 1,
        kind=kind,
        published_by=actor,
        changes=changes,
        slots=[_slot(match) for match in scheduling.plannable(tournament) if match.scheduled_at],
        **extra,
    )
    if any(change["notify"] for change in changes):
        outbox.enqueue(NOTIFY, f"{NOTIFY}:{version.id}", {"version_id": str(version.id)})
    return version


def _refuse_conflicts(conflicts: list) -> None:
    if conflicts:
        raise ApiException(
            "schedule_conflicts",
            conflicts[0]["message"],
            409,
            extra={"conflicts": [{**c, "match_id": str(c["match_id"])} for c in conflicts]},
        )


def publish(tournament: Tournament, actor, note: str = "") -> ScheduleVersion:
    """Publish the working plan. Refused while it has conflicts, or when there is nothing new."""
    conflicts, _ = scheduling.check(tournament, {})
    _refuse_conflicts(conflicts)
    matches = scheduling.plannable(tournament)
    moves = [
        (match, match.draft_table, match.draft_at)
        for match in matches
        if (match.draft_table_id, match.draft_at) != (match.planned_table_id, match.scheduled_at)
    ]
    if not moves:
        raise ApiException("nothing_to_publish", "The published schedule already matches the plan.", 409)
    return _record(tournament, actor, ScheduleVersion.Kind.PUBLISHED, moves, note=note)


def delay(tournament: Tournament, actor, table, minutes: int, reason: str, note: str = "") -> dict:
    """Move every published match still to play on `table` on by `minutes`, then everything that
    then clashes with them, and publish that. The working plan follows where it hadn't been changed."""
    matches = scheduling.plannable(tournament)
    items = scheduling.items_for(matches)
    plans = {pk: scheduling.Plan(item, *scheduling.published(item)) for pk, item in items.items()}
    late = [plan for plan in plans.values() if plan.at and plan.table and plan.table.id == table.id]
    if not late:
        raise ApiException("nothing_planned", f"No published match still to play is on {table.label}.", 409)
    for plan in late:
        plan.at += timedelta(minutes=minutes)
    scheduling.push_on(plans)
    moves = []
    for pk, plan in plans.items():
        match = items[pk].match
        if plan.at != match.scheduled_at:
            if (match.draft_table_id, match.draft_at) == (match.planned_table_id, match.scheduled_at):
                match.draft_table, match.draft_at = plan.table, plan.at
                match.save(update_fields=["draft_table", "draft_at"])
            moves.append((match, plan.table, plan.at))
    version = _record(
        tournament,
        actor,
        ScheduleVersion.Kind.DELAY,
        moves,
        reason=reason,
        note=note,
        delayed_table=table,
        delay_minutes=minutes,
    )
    conflicts, warnings = scheduling.check(tournament, {}, plan_of=scheduling.published)
    return {"version": version, "conflicts": conflicts, "warnings": warnings}


def _when(value: str | None, zone: ZoneInfo) -> str:
    if not value:
        return "no time yet"
    return f"{datetime.fromisoformat(value).astimezone(zone):%a %d %b %H:%M}"


def _where(side: dict, zone: ZoneInfo) -> str:
    table = side["table"]["label"] if side["table"] else "table to be confirmed"
    return f"{_when(side['scheduled_at'], zone)}, {table}"


@outbox.handler(NOTIFY)
def notify(payload: dict) -> None:
    """Tell each player and umpire of the version's moved matches about their own, once."""
    from scoring.models import Scorecard

    version = ScheduleVersion.objects.select_related("tournament").filter(pk=payload["version_id"]).first()
    if version is None or version.notified_at:
        return
    tournament = version.tournament
    zone = ZoneInfo(tournament.timezone)
    moved = {change["match_id"]: change for change in version.changes if change["notify"]}
    matches = Match.objects.filter(pk__in=moved).prefetch_related(
        "entry_a__players__user", "entry_b__players__user"
    )
    umpires = {
        str(card.match_id): card.umpire
        for card in Scorecard.objects.filter(match_id__in=moved, umpire__isnull=False).select_related(
            "umpire"
        )
    }
    lines_for: dict = {}
    for match in matches:
        change = moved[str(match.id)]
        line = (
            f"- {change['label']} ({change['title']}): now {_where(change['after'], zone)}; "
            f"was {_where(change['before'], zone)}."
        )
        people = [
            place.user for entry in (match.entry_a, match.entry_b) if entry for place in entry.players.all()
        ]
        if str(match.id) in umpires:
            people.append(umpires[str(match.id)])
        for user in people:
            lines_for.setdefault(user, []).append(line)
    sent = 0
    why = {"late_start": "a table started late", "out_of_service": "a table is out of service"}.get(
        version.reason, "the organizers changed the schedule"
    )
    for user, lines in lines_for.items():
        if not user.can_receive_email:  # a guest: club staff pass the news on
            continue
        body = (
            f"The schedule of {tournament.name} has changed because {why}. Your matches:\n\n"
            + "\n".join(lines)
            + "\n\nTimes are the venue's local time and are estimates only."
            + (f"\n\nFrom the organizers: {version.note}" if version.note else "")
            + f"\n\nSee the tournament: {settings.FRONTEND_URL}/tournaments/{tournament.id}"
        )
        try:
            send_mail(f"Schedule change at {tournament.name}", body, None, [user.email])
            sent += 1
        except Exception:
            # Retrying the job would mail the others twice: the version page still lists the change.
            logger.exception("schedule change not sent to user %s for version %s", user.id, version.id)
    version.notified_at = timezone.now()
    version.notified_count = sent
    version.save(update_fields=["notified_at", "notified_count"])
