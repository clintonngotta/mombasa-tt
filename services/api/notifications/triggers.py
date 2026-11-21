"""What raises an alert (REQ-019). Each trigger names the subject and the version it describes, so a
retry or a repeated call never makes a second alert, and a newer version supersedes older ones."""

from .models import Category
from .service import notify, supersede


def _tournament_link(event) -> str:
    return f"/tournaments/{event.tournament_id}"


def entry_decided(entry, status: str) -> None:
    words = {
        "accepted": "You're in",
        "waitlisted": "You're on the waiting list",
        "rejected": "Your entry wasn't accepted",
    }
    if status not in words:
        return
    event = entry.event
    players = [p.user_id for p in entry.players.all()]
    notify(
        players,
        Category.REGISTRATION,
        f"{words[status]}: {event.tournament.name}, {event.name}",
        body=entry.reason if status == "rejected" else "",
        subject=f"entry:{entry.id}",
        version=status,
        link=_tournament_link(event),
        organization=event.tournament.organization,
    )


def _match_link(match) -> str:
    event = match.draw.event
    return f"/tournaments/{event.tournament_id}/events/{event.id}/matches/{match.id}"


def up_next(match, players) -> None:
    """The match is next in line for a table: get ready. Once per match; the call supersedes it."""
    event = match.draw.event
    notify(
        players,
        Category.UP_NEXT,
        "You're up next",
        body=f"{event.name}: your match is next in line for a table. Stay close to the hall.",
        subject=f"match:{match.id}",
        version="up-next",
        link=_match_link(match),
        organization=event.tournament.organization,
    )


def called_to_table(match, reservation, players) -> None:
    supersede(f"match:{match.id}", Category.UP_NEXT)
    notify(
        players,
        Category.TABLE_CALL,
        f"Called to {reservation.table.label}",
        body=f"{match.draw.event.name}: go to {reservation.table.label} now.",
        subject=f"match:{match.id}",
        version=str(reservation.id),
        link=_match_link(match),
        organization=match.draw.event.tournament.organization,
    )


def taken_off_table(match, players, reason: str) -> None:
    supersede(f"match:{match.id}", Category.TABLE_CALL)
    notify(
        players,
        Category.ASSIGNMENT,
        "Your match was taken off its table",
        body=reason,
        subject=f"match:{match.id}",
        version=f"recalled:{match.dispatched_at.isoformat() if match.dispatched_at else ''}",
        link=_match_link(match),
        organization=match.draw.event.tournament.organization,
    )


def ceremony_published(tournament, players) -> None:
    notify(
        players,
        Category.ANNOUNCEMENT,
        f"Winners of {tournament.name}",
        body="The award ceremony is published.",
        subject=f"ceremony:{tournament.id}",
        link=f"/tournaments/{tournament.id}/ceremony",
        organization=tournament.organization,
    )


def session_invited(session, users) -> None:
    notify(
        users,
        Category.TRAINING,
        f"Invited: {session.title}",
        body=f"{session.organization.name} invites you. Answer under Training.",
        subject=f"club-session:{session.id}",
        link="/training",
        organization=session.organization,
    )


def challenged(challenge) -> None:
    notify(
        [challenge.challenged_id],
        Category.SODA,
        f"{challenge.challenger.display_name} challenged you to a soda game",
        body=challenge.message,
        subject=f"soda:{challenge.id}",
        version="challenge",
        link="/play/soda",
    )


def result_recorded(challenge, recorder) -> None:
    other = challenge.challenged_id if recorder.pk == challenge.challenger_id else challenge.challenger_id
    notify(
        [other],
        Category.SODA,
        f"{recorder.display_name} recorded your soda game: confirm or dispute it",
        subject=f"soda:{challenge.id}",
        version=f"result:{challenge.result.updated_at.isoformat()}",
        link="/play/soda",
    )


def external_event_reviewed(event) -> None:
    if event.submitted_by_id is None:
        return
    approved = event.review == "approved"
    notify(
        [event.submitted_by_id],
        Category.EVENTS,
        f"{event.name} is {'listed' if approved else 'not listed'}",
        body="" if approved else event.review_note,
        subject=f"external-event:{event.id}",
        version=event.review,
        link="/club/external-events",
        organization=event.submitted_by_org,
    )


def activity_news(activity, what: str) -> None:
    """Publishing, a change of time or place, and cancelling reach the activity's audience only."""
    from organizations.models import Membership

    if activity.audience == "selected":
        audience = set(activity.invitees.values_list("pk", flat=True))
    else:
        audience = set(
            Membership.objects.active()
            .filter(organization=activity.organization)
            .values_list("user_id", flat=True)
        )
    titles = {
        "published": f"New: {activity.title}",
        "changed": f"Changed: {activity.title}",
        "cancelled": f"Cancelled: {activity.title}",
    }
    body = activity.cancel_reason if what == "cancelled" else activity.place
    version = what if what != "changed" else f"changed:{activity.starts_at.isoformat()}:{activity.place}"
    notify(
        audience,
        Category.ACTIVITY,
        titles[what],
        body=body,
        subject=f"activity:{activity.id}",
        version=version[:80],
        link=f"/activities/{activity.organization_id}/{activity.id}",
        organization=activity.organization,
    )


def booking_news(booking) -> None:
    words = {"approved": "approved", "rejected": "not approved", "cancelled": "cancelled"}
    if booking.status not in words:
        return
    notify(
        [booking.requester_id],
        Category.BOOKING,
        f"Your booking at {booking.venue.name} is {words[booking.status]}",
        body=booking.reason,
        subject=f"booking:{booking.id}",
        version=booking.status,
        link="/profile/bookings",
        organization=booking.venue.organization,
    )


def due_reminder(charge, state: str, outstanding_minor: int, version: str | None = None) -> int:
    """A contribution due that falls today ("due") or has passed unpaid ("overdue"). Each is sent once;
    a staff nudge carries its own version, so it goes at most once a day."""
    amount = f"{charge.currency} {outstanding_minor / 100:,.0f}"
    title = (
        f"{charge.purpose}: {amount} due today"
        if state == "due"
        else f"{charge.purpose}: {amount} is overdue since {charge.due_on:%d %b}"
    )
    return notify(
        [charge.member_id],
        Category.DUES,
        title,
        subject=f"due:{charge.id}",
        version=version or state,
        link="/club/my-payments",
        organization=charge.organization,
    )


def welfare_opened(project) -> None:
    """Tell the audience a welfare project is open. Only that: never its title, description or who it
    is for, which may carry a member's health or circumstances (REQ-038)."""
    from finance.models import WelfareProject
    from organizations.models import Membership

    if project.audience == WelfareProject.Audience.SELECTED:
        audience = list(project.audience_members.values_list("pk", flat=True))
    else:
        audience = list(
            Membership.objects.active()
            .filter(organization=project.organization)
            .values_list("user_id", flat=True)
        )
    notify(
        [u for u in audience if u != project.beneficiary_id],
        Category.ANNOUNCEMENT,
        f"{project.organization.name} opened a welfare project",
        subject=f"welfare:{project.id}",
        link="/club/welfare",
        organization=project.organization,
    )
