"""Coaching rules (REQ-047): who may see what, when a session may be booked, and free times to offer."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from competitions.models import Match
from core.exceptions import ApiException
from training import service as training

from .models import Availability, Coaching, CoachProfile

SHORTEST = timedelta(minutes=30)
LONGEST = timedelta(hours=3)
BOOK_AHEAD = timedelta(days=90)
SLOT_STEP = timedelta(minutes=30)


def active_coaching(coach, coaching_id) -> Coaching:
    """The caller's active coaching of a trainee, or 404: a coach sees a trainee only while they coach
    them."""
    return get_object_or_404(
        Coaching.objects.select_related("trainee"), pk=coaching_id, coach=coach, status=Coaching.Status.ACTIVE
    )


def coaches(coach, trainee) -> bool:
    return Coaching.objects.filter(coach=coach, trainee=trainee, status=Coaching.Status.ACTIVE).exists()


def official_matches(user):
    """Official matches the user played in (singles, doubles or a team tie), most recent first."""
    plays = Q(entry_a__players__user=user) | Q(entry_b__players__user=user) | Q(rubbers__players__user=user)
    return (
        Match.objects.filter(plays)
        .exclude(status=Match.Status.BYE)
        .select_related("draw__event__tournament", "entry_a", "entry_b", "winner")
        .distinct()
    )


def lock_people(*users) -> None:
    """Lock both people's rows in a fixed order so two bookings can't take the same time at once."""
    ids = sorted(str(u.pk) for u in users)
    list(get_user_model().objects.select_for_update().filter(pk__in=ids).order_by("pk"))


def _local(profile: CoachProfile, moment: datetime) -> datetime:
    return moment.astimezone(ZoneInfo(profile.timezone))


def inside_availability(profile: CoachProfile, starts: datetime, ends: datetime) -> bool:
    start, end = _local(profile, starts), _local(profile, ends)
    if start.date() != end.date() and not (end.time().hour == 0 and end.time().minute == 0):
        return False
    windows = Availability.objects.filter(coach=profile.user, weekday=start.weekday())
    return any(w.starts <= start.time() and (end.time() <= w.ends) for w in windows)


def check_booking(profile: CoachProfile, trainee, starts: datetime, ends: datetime) -> None:
    """Refuse a booking the coach doesn't take. Calendar clashes are checked separately, with both
    people locked."""
    if profile.user_id == trainee.pk:
        raise ApiException("own_booking", "You can't book a session with yourself.")
    if not (profile.accepting or coaches(profile.user, trainee)):
        raise ApiException("not_accepting", "This coach isn't taking new players at the moment.")
    now = timezone.now()
    if starts <= now:
        raise ApiException("past_booking", "Choose a time that hasn't passed.")
    if starts > now + BOOK_AHEAD:
        raise ApiException("too_far_ahead", "Book at most 90 days ahead.")
    if not (SHORTEST <= ends - starts <= LONGEST):
        raise ApiException("booking_length", "A session lasts between 30 minutes and 3 hours.")
    if not inside_availability(profile, starts, ends):
        raise ApiException("outside_availability", "The coach doesn't take sessions at that time.")


def free_slots(profile: CoachProfile, first: date, days: int, minutes: int) -> list[dict]:
    """Start times, every half hour inside the coach's weekly windows, when a session of `minutes`
    fits around everything already in the coach's calendar."""
    tz = ZoneInfo(profile.timezone)
    length = timedelta(minutes=minutes)
    window_start = datetime.combine(first, datetime.min.time(), tz)
    window_end = window_start + timedelta(days=days)
    busy = [
        (c["starts_at"], c["ends_at"]) for c in training.conflicts(profile.user, window_start, window_end)
    ]
    weekly: dict[int, list[Availability]] = {}
    for window in Availability.objects.filter(coach=profile.user):
        weekly.setdefault(window.weekday, []).append(window)
    earliest = timezone.now() + timedelta(hours=1)
    slots = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        for window in weekly.get(day.weekday(), []):
            start = datetime.combine(day, window.starts, tz)
            last = datetime.combine(day, window.ends, tz) - length
            while start <= last:
                end = start + length
                if start >= earliest and not any(s < end and e > start for s, e in busy):
                    slots.append({"starts_at": start, "ends_at": end, "venue": window.venue})
                start += SLOT_STEP
    return slots


def plan_progress(plan) -> dict:
    items = list(plan.items.all())
    return {"done": sum(1 for i in items if i.completed_at), "total": len(items)}
