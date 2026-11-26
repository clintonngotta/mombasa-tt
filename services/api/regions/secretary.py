"""Who does the secretary's work at a meeting (REQ-046): writing the minutes, taking attendance and
issuing the meeting's penalties."""

from organizations.access import effective_permissions
from organizations.permissions import Permission

MINUTES = Permission.MINUTES_MANAGE


def is_secretary(user, meeting, granted: frozenset[str] | None = None) -> bool:
    """The secretary named on the meeting, or a holder of `minutes.manage` in the host (its Secretary
    role). Pass `granted`, the user's effective permissions in the host, when already known."""
    if meeting.secretary_id is not None and meeting.secretary_id == user.pk:
        return True
    if granted is None:
        granted = effective_permissions(user, meeting.organization)
    return MINUTES in granted
