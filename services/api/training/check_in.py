"""Training rules and location check-in (REQ-052).

A club sets where it usually trains, when check-in opens and closes around a session's start, when a
check-in counts as late, and from how far (at most 300 m) a member may check in. A member checks in from
their phone: the API measures the distance from the session's location to the position the phone sends,
refuses a position less sure than the radius, and keeps only the distance, the accuracy and the time.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.exceptions import ApiException
from core.nearby import metres_between

from .models import MAX_RADIUS_M, ClubSession, SessionInvitation, TrainingRules

DEFAULTS = {
    "slots": [],
    "venue": None,
    "latitude": None,
    "longitude": None,
    "location_label": "",
    "opens_before_minutes": 30,
    "closes_after_minutes": 30,
    "late_after_minutes": 10,
    "radius_m": MAX_RADIUS_M,
}


def rules_for(organization) -> TrainingRules:
    """The organization's rules, or the defaults (unsaved) when it has set none."""
    found = TrainingRules.objects.filter(organization=organization).select_related("venue").first()
    return found or TrainingRules(organization=organization)


def _point(venue, latitude, longitude, label):
    if venue is not None and venue.latitude is not None and venue.longitude is not None:
        return {"latitude": venue.latitude, "longitude": venue.longitude, "label": label or venue.name}
    if latitude is not None and longitude is not None:
        return {"latitude": latitude, "longitude": longitude, "label": label}
    return None


def location_of(session: ClubSession, rules: TrainingRules) -> dict | None:
    """Where check-in for the session is measured from: the session's own location when staff moved it,
    else the club's usual place, else the venue of its tables. None when no position is known. `moved`
    says the session isn't at the usual place."""
    moved = _point(
        session.location_venue, session.location_latitude, session.location_longitude, session.location_label
    )
    if moved:
        return {**moved, "moved": True}
    usual = _point(rules.venue, rules.latitude, rules.longitude, rules.location_label)
    if usual:
        return {**usual, "moved": False}
    for table in session.tables.all():
        found = _point(table.venue, None, None, "")
        if found:
            return {**found, "moved": False}
    return None


def window(session: ClubSession, rules: TrainingRules) -> dict:
    return {
        "opens_at": session.starts_at - timedelta(minutes=rules.opens_before_minutes),
        "closes_at": session.starts_at + timedelta(minutes=rules.closes_after_minutes),
        "late_after": session.starts_at + timedelta(minutes=rules.late_after_minutes),
    }


@transaction.atomic
def check_in(invitation: SessionInvitation, *, latitude, longitude, accuracy_m) -> SessionInvitation:
    """The member says they are at the session. Nothing of the position is stored but how far it was from
    the session's location and how accurate the phone said it was."""
    invitation = (
        SessionInvitation.objects.select_for_update(of=("self",))
        .select_related("session__organization", "session__location_venue")
        .get(pk=invitation.pk)
    )
    session = invitation.session
    if invitation.attended is not None:
        return invitation  # already marked, by them or by staff: nothing changes
    if session.status != ClubSession.Status.SCHEDULED:
        raise ApiException("session_cancelled", "This session was cancelled.", 409)
    if invitation.status == SessionInvitation.Status.DECLINED:
        raise ApiException("declined", "You declined this session. Accept it first.", 409)
    rules = rules_for(session.organization)
    times = window(session, rules)
    now = timezone.now()
    if now < times["opens_at"]:
        raise ApiException("check_in_not_open", "Check-in hasn't opened yet.", 409)
    if now > times["closes_at"]:
        raise ApiException("check_in_closed", "Check-in has closed. Ask the coach to mark you.", 409)
    place = location_of(session, rules)
    if place is None:
        raise ApiException(
            "no_location", "The club hasn't set where it trains. Ask the coach to mark you.", 409
        )
    if accuracy_m > rules.radius_m:
        raise ApiException(
            "position_inaccurate",
            "Your phone isn't sure enough of where you are. Try again outdoors.",
            409,
        )
    distance = round(metres_between(place["latitude"], place["longitude"], latitude, longitude))
    if distance > rules.radius_m:
        raise ApiException(
            "too_far",
            f"You're about {distance} m from the session. Check in within {rules.radius_m} m of it.",
            409,
        )
    invitation.attended = True
    invitation.attendance_source = SessionInvitation.Source.SELF
    invitation.attendance_by = None
    invitation.attendance_at = now
    invitation.late = now > times["late_after"]
    invitation.check_in_distance_m = distance
    invitation.check_in_accuracy_m = round(accuracy_m)
    invitation.save(
        update_fields=[
            "attended",
            "attendance_source",
            "attendance_by",
            "attendance_at",
            "late",
            "check_in_distance_m",
            "check_in_accuracy_m",
        ]
    )
    return invitation
