"""Who sees an activity, answering one, and the club schedule (REQ-039, TASK-072)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from competitions.models import Tournament
from core.exceptions import ApiException
from organizations.access import effective_permissions
from organizations.models import Membership, Organization
from organizations.permissions import Permission
from training.models import ClubSession

from .models import Activity, Rsvp

MANAGE = Permission.ACTIVITIES_MANAGE
SHOWN = [Activity.Status.PUBLISHED, Activity.Status.CANCELLED]
TOURNAMENTS_SHOWN = [Tournament.Status.PUBLISHED, Tournament.Status.IN_PROGRESS, Tournament.Status.COMPLETED]


def is_staff(user, organization: Organization) -> bool:
    return MANAGE in effective_permissions(user, organization)


def is_member(user, organization: Organization) -> bool:
    return Membership.objects.active().filter(user=user, organization=organization).exists()


def visible(user, organization: Organization):
    """Activities of `organization` the user may see. Staff see drafts too. Members see what is
    published or cancelled for all members or for them; anyone signed in sees public ones."""
    activities = organization.activities.all()
    if is_staff(user, organization):
        return activities
    # A visit for a welfare project the beneficiary had hidden goes from member views with it.
    activities = activities.exclude(welfare_project__hidden_at__isnull=False)
    public = Q(public=True, status__in=SHOWN)
    if not is_member(user, organization):
        return activities.filter(public)
    mine = Q(status__in=SHOWN) & (Q(audience=Activity.Audience.MEMBERS) | Q(invitees=user))
    return activities.filter(mine | public).distinct()


def in_audience(user, activity: Activity) -> bool:
    if not is_member(user, activity.organization):
        return False
    if activity.welfare_project_id and activity.welfare_project.hidden_at:
        return False
    return activity.audience == Activity.Audience.MEMBERS or activity.invitees.filter(pk=user.pk).exists()


def going_count(activity: Activity) -> int:
    return activity.rsvps.filter(answer=Rsvp.Answer.GOING, waitlisted=False).count()


@transaction.atomic
def answer(activity: Activity, user, value: str) -> Rsvp:
    """Record the member's answer. The activity row is locked, so "going" answers sent at the same
    moment queue up: once the places are taken, the rest wait on the list."""
    activity = Activity.objects.select_for_update().select_related("organization").get(pk=activity.pk)
    if not in_audience(user, activity):
        raise ApiException("not_invited", "This activity is for other members.", 403)
    if activity.status != Activity.Status.PUBLISHED:
        raise ApiException("activity_closed", "This activity isn't taking answers.", 409)
    now = timezone.now()
    if activity.ends_at <= now or (activity.rsvp_deadline and activity.rsvp_deadline <= now):
        raise ApiException("rsvp_closed", "Answers for this activity have closed.", 409)
    rsvp = Rsvp.objects.filter(activity=activity, user=user).first()
    holding = rsvp is not None and rsvp.answer == Rsvp.Answer.GOING and not rsvp.waitlisted
    waitlisted = False
    if value == Rsvp.Answer.GOING and not holding and activity.capacity is not None:
        waitlisted = going_count(activity) >= activity.capacity
    if rsvp is None:
        return Rsvp.objects.create(activity=activity, user=user, answer=value, waitlisted=waitlisted)
    if value == Rsvp.Answer.GOING and holding:
        return rsvp  # already has a place
    rsvp.answer, rsvp.waitlisted = value, waitlisted
    rsvp.save(update_fields=["answer", "waitlisted", "updated_at"])
    return rsvp


def _day_bounds(day, zone: str) -> datetime:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(zone))


def schedule(user, organization: Organization, *, when: str = "upcoming", kinds=None) -> list[dict]:
    """The club schedule (REQ-039): activities the member may see, the organization's published
    tournaments, and its club training sessions, in date order. Upcoming means not yet over."""
    kinds = set(kinds or ["activity", "tournament", "training"])
    now = timezone.now()
    items = []
    if "activity" in kinds:
        for activity in visible(user, organization).exclude(status=Activity.Status.DRAFT):
            items.append(
                {
                    "kind": "activity",
                    "id": activity.id,
                    "title": activity.title,
                    "detail": activity.get_kind_display(),
                    "starts_at": activity.starts_at,
                    "ends_at": activity.ends_at,
                    "place": activity.place,
                    "cancelled": activity.status == Activity.Status.CANCELLED,
                }
            )
    if "tournament" in kinds:
        for tournament in organization.tournaments.filter(status__in=TOURNAMENTS_SHOWN).select_related(
            "venue"
        ):
            items.append(
                {
                    "kind": "tournament",
                    "id": tournament.id,
                    "title": tournament.name,
                    "detail": "Tournament",
                    "starts_at": _day_bounds(tournament.starts_on, tournament.timezone),
                    "ends_at": _day_bounds(tournament.ends_on + timedelta(days=1), tournament.timezone),
                    "place": tournament.venue.name if tournament.venue else "",
                    "cancelled": False,
                }
            )
    if "training" in kinds:
        sessions = ClubSession.objects.filter(organization=organization).prefetch_related("tables__venue")
        for session in sessions:
            venues = sorted({table.venue.name for table in session.tables.all()})
            items.append(
                {
                    "kind": "training",
                    "id": session.id,
                    "title": session.title,
                    "detail": "Training session",
                    "starts_at": session.starts_at,
                    "ends_at": session.ends_at,
                    "place": ", ".join(venues),
                    "cancelled": session.status == ClubSession.Status.CANCELLED,
                }
            )
    if when == "past":
        items = [item for item in items if item["ends_at"] <= now]
        return sorted(items, key=lambda item: item["starts_at"], reverse=True)
    items = [item for item in items if item["ends_at"] > now]
    return sorted(items, key=lambda item: item["starts_at"])


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _stamp(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    """RFC 5545 lines are at most 75 octets; longer ones continue on lines starting with a space."""
    encoded = line.encode()
    if len(encoded) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        piece = char.encode()
        if len(current) + len(piece) > (75 if not parts else 74):
            parts.append(current.decode())
            current = b""
        current += piece
    parts.append(current.decode())
    return "\r\n ".join(parts)


def ics(organization: Organization, items: list[dict]) -> str:
    """The schedule as an iCalendar file to add to a phone's calendar."""
    now = _stamp(timezone.now())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Coast TT//Club schedule//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(organization.name)}",
    ]
    for item in items:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{item['kind']}-{item['id']}@coast-tt",
            f"DTSTAMP:{now}",
            f"DTSTART:{_stamp(item['starts_at'])}",
            f"DTEND:{_stamp(item['ends_at'])}",
            f"SUMMARY:{_escape(item['title'])}",
            f"CATEGORIES:{_escape(item['detail'])}",
        ]
        if item["place"]:
            lines.append(f"LOCATION:{_escape(item['place'])}")
        if item["cancelled"]:
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def check_welfare_link(
    user, organization: Organization, project_id, *, audience, invitee_ids, public, changed=True
):
    """The welfare project a visit may be linked to, or None. Linking or unlinking (`changed`) takes
    welfare.manage too, and links only an open project of the club. Whenever linked, the visit is never
    public, and when the project is for selected members it is for some of them (or the beneficiary)."""
    from finance import welfare
    from finance.models import WelfareProject
    from organizations.committee import local_today

    if changed and Permission.WELFARE_MANAGE not in effective_permissions(user, organization):
        raise ApiException("permission_denied", "Linking a welfare project takes welfare.manage.", 403)
    if project_id is None:
        return None
    project = WelfareProject.objects.filter(organization=organization, pk=project_id).first()
    if project is None:
        raise ApiException("bad_welfare_project", "Choose one of the club's welfare projects.", 400)
    if changed and welfare.is_closed(project, local_today(organization)):
        raise ApiException("project_closed", "That welfare project is closed.", 409)
    if public:
        raise ApiException("welfare_not_public", "A welfare visit can't be public.", 400)
    if project.audience == WelfareProject.Audience.SELECTED:
        allowed = set(project.audience_members.values_list("pk", flat=True)) | {project.beneficiary_id}
        if audience != Activity.Audience.SELECTED or not set(invitee_ids or ()) <= allowed:
            raise ApiException(
                "outside_welfare_audience", "Invite only members the welfare project is for.", 400
            )
    return project
