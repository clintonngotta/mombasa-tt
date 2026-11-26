"""Calendar commitments of personal training (REQ-027, TASK-043).

A training session in a plan occupies the player's time; a checklist item doesn't. A session may not
overlap the player's other sessions, a club session they accepted (TASK-044), a coaching session booked
with or by them (REQ-047), or a match they
are scheduled to play (a published draw's match with a
planned time, lasting as long as the schedule expects it to). The check runs with the player's user row
locked, so two sessions saved at the same moment can't both slip into the same hour.
"""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q

from coaching.models import Booking
from competitions.models import DrawVersion, Match
from competitions.scheduling import match_minutes
from core.exceptions import ApiException
from organizations.models import Membership

from .models import ClubSession, Drill, PlanItem, SessionInvitation

LONGEST_MATCH = timedelta(hours=3)  # how far back a match can start and still overlap


def lock_player(user) -> None:
    get_user_model().objects.select_for_update().filter(pk=user.pk).first()


def conflicts(
    user,
    starts: datetime,
    ends: datetime,
    exclude: PlanItem | None = None,
    exclude_booking=None,
    with_coach=None,
) -> list[dict]:
    """`with_coach`: a booked session with this coach and a session in a plan they gave are the same
    hour on the table (the plan session is its running order), so those two never clash."""
    found = []
    sessions = PlanItem.objects.filter(
        plan__owner=user, kind=PlanItem.Kind.SESSION, starts_at__lt=ends, ends_at__gt=starts
    ).select_related("plan")
    if exclude is not None:
        sessions = sessions.exclude(pk=exclude.pk)
    if with_coach is not None:
        sessions = sessions.exclude(plan__coach=with_coach)
    for item in sessions:
        found.append(
            {"kind": "training", "title": item.title, "starts_at": item.starts_at, "ends_at": item.ends_at}
        )
    bookings = Booking.objects.filter(
        Q(coach=user) | Q(trainee=user), status__in=Booking.HOLDING, starts_at__lt=ends, ends_at__gt=starts
    ).select_related("coach", "trainee")
    if exclude_booking is not None:
        bookings = bookings.exclude(pk=exclude_booking.pk)
    if with_coach is not None:
        bookings = bookings.exclude(coach=with_coach, trainee=user)
    for booking in bookings:
        other = booking.trainee if booking.coach_id == user.pk else booking.coach
        found.append(
            {
                "kind": "booking",
                "title": f"Coaching session with {other.display_name}",
                "starts_at": booking.starts_at,
                "ends_at": booking.ends_at,
            }
        )
    accepted = SessionInvitation.objects.filter(
        user=user,
        status=SessionInvitation.Status.ACCEPTED,
        session__status=ClubSession.Status.SCHEDULED,
        session__starts_at__lt=ends,
        session__ends_at__gt=starts,
    ).select_related("session__organization")
    for invitation in accepted:
        session = invitation.session
        found.append(
            {
                "kind": "club_session",
                "title": f"{session.organization.name}: {session.title}",
                "starts_at": session.starts_at,
                "ends_at": session.ends_at,
            }
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


def ensure_free(
    user,
    starts: datetime,
    ends: datetime,
    exclude: PlanItem | None = None,
    *,
    exclude_booking=None,
    with_coach=None,
    message="You already have something on at that time.",
) -> None:
    """409 with the clashing commitments when the player isn't free. Call with `lock_player` held."""
    clashes = conflicts(user, starts, ends, exclude, exclude_booking, with_coach)
    if clashes:
        raise ApiException(
            "calendar_conflict",
            message,
            409,
            extra={
                "conflicts": [
                    {**c, "starts_at": c["starts_at"].isoformat(), "ends_at": c["ends_at"].isoformat()}
                    for c in clashes
                ]
            },
        )


def usable_drills(user):
    """Drills a player may see and put in their plans: the standard library, their own, and those of
    clubs they are an active member of."""
    clubs = Membership.objects.active().filter(user=user).values("organization")
    standard = Q(owner__isnull=True, organization__isnull=True)
    return Drill.objects.filter(standard | Q(owner=user) | Q(organization__in=clubs))


def readable_drills(user):
    """Drills a player may open: the ones they may use, and any drill in a plan of theirs. A coach may
    put their own drill in a trainee's plan, and the trainee must be able to read it."""
    items = PlanItem.objects.filter(plan__owner=user)
    in_plans = {
        activity.get("drill")
        for activities in items.filter(kind=PlanItem.Kind.SESSION).values_list("activities", flat=True)
        for activity in activities
    } - {None}
    return Drill.objects.filter(
        Q(pk__in=usable_drills(user).values("pk"))
        | Q(pk__in=items.filter(drill__isnull=False).values("drill"))
        | Q(pk__in=in_plans)
    )


LEVELS = ["beginner", "intermediate", "advanced"]


def recommend(drills, skills: list[str], *, exclude=(), limit: int = 6) -> list[dict]:
    """Drills that teach the most of `skills`, best first: more goal skills taught, then drills built
    around a goal skill (listed first), then fewer other skills, then the standard library before the
    rest, then by level and title."""
    wanted = set(skills)
    if not wanted:
        return []
    found = []
    for drill in drills.filter(skills__overlap=list(wanted)).exclude(pk__in=list(exclude)):
        matched = [skill for skill in drill.skills if skill in wanted]
        standard = drill.owner_id is None and drill.organization_id is None
        level = LEVELS.index(drill.level) if drill.level in LEVELS else len(LEVELS)
        # A drill listing a goal skill first is built around it.
        primary = drill.skills.index(matched[0])
        key = (
            -len(matched),
            primary,
            len(drill.skills) - len(matched),
            not standard,
            level,
            drill.title.lower(),
        )
        found.append((key, {"drill": drill, "matched": matched}))
    return [item for _, item in sorted(found, key=lambda pair: pair[0])[:limit]]
