"""Calendar commitments of personal training (REQ-027, TASK-043).

A training session in a plan occupies the player's time; a checklist item doesn't. A session may not
overlap the player's other sessions or a match they are scheduled to play (a published draw's match with a
planned time, lasting as long as the schedule expects it to). The check runs with the player's user row
locked, so two sessions saved at the same moment can't both slip into the same hour.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q

from competitions.models import DrawVersion, Match
from competitions.scheduling import match_minutes
from core.exceptions import ApiException
from organizations.models import Membership

from .models import Drill, PlanItem

LONGEST_MATCH = timedelta(hours=3)  # how far back a match can start and still overlap


def lock_player(user) -> None:
    get_user_model().objects.select_for_update().filter(pk=user.pk).first()


def conflicts(user, starts: datetime, ends: datetime, exclude: PlanItem | None = None) -> list[dict]:
    found = []
    sessions = PlanItem.objects.filter(
        plan__owner=user, kind=PlanItem.Kind.SESSION, starts_at__lt=ends, ends_at__gt=starts
    ).select_related("plan")
    if exclude is not None:
        sessions = sessions.exclude(pk=exclude.pk)
    for item in sessions:
        found.append(
            {"kind": "training", "title": item.title, "starts_at": item.starts_at, "ends_at": item.ends_at}
        )
    plays = Q(entry_a__players__user=user, entry_a__players__live=True) | Q(
        entry_b__players__user=user, entry_b__players__live=True
    )
    matches = (
        Match.objects.filter(
            plays,
            status=Match.Status.SCHEDULED,
            draw__status=DrawVersion.Status.PUBLISHED,
            scheduled_at__lt=ends,
            scheduled_at__gt=starts - LONGEST_MATCH,
        )
        .select_related("draw__event__tournament")
        .distinct()
    )
    for match in matches:
        event = match.draw.event
        match_ends = match.scheduled_at + timedelta(minutes=match_minutes(event))
        if match_ends > starts:
            found.append(
                {
                    "kind": "match",
                    "title": f"{event.tournament.name}: {event.name}",
                    "starts_at": match.scheduled_at,
                    "ends_at": match_ends,
                }
            )
    return sorted(found, key=lambda c: c["starts_at"])


def ensure_free(user, starts: datetime, ends: datetime, exclude: PlanItem | None = None) -> None:
    """409 with the clashing commitments when the player isn't free. Call with `lock_player` held."""
    clashes = conflicts(user, starts, ends, exclude)
    if clashes:
        raise ApiException(
            "calendar_conflict",
            "You already have something on at that time.",
            409,
            extra={
                "conflicts": [
                    {**c, "starts_at": c["starts_at"].isoformat(), "ends_at": c["ends_at"].isoformat()}
                    for c in clashes
                ]
            },
        )


def usable_drills(user):
    """Drills a player may put in their plans: their own and those of clubs they are an active member of."""
    clubs = Membership.objects.active().filter(user=user).values("organization")
    return Drill.objects.filter(Q(owner=user) | Q(organization__in=clubs))
