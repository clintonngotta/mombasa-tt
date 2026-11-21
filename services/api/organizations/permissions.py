"""Permission catalog and role templates (REQ-005).

A permission is a stable code. Roles hold sets of codes; a member's effective permissions in an
organization are the union of their roles' codes plus the organization's Member role, which applies to
every active member. Granting authority never exceeds the acting user's own effective permissions.
"""

from django.db import models


class Permission(models.TextChoices):
    MEMBERS_MANAGE = "members.manage", "Invite members, decide join requests and remove members"
    ROLES_MANAGE = "roles.manage", "Create and edit roles and assign them to members"
    COMPETITIONS_MANAGE = "competitions.manage", "Set up and run tournaments, events and match days"
    RESULTS_MANAGE = "results.manage", "Confirm and correct official results"
    RESULTS_REFEREE = "results.referee", "Award walkovers and disqualifications as the referee"
    SCORING_ASSIGNED = "scoring.assigned", "Score matches they are assigned to"
    FACILITIES_MANAGE = "facilities.manage", "Manage venues, tables, opening hours and bookings"
    FINANCES_VIEW = "finances.view", "See club finances and contribution records"
    FINANCES_MANAGE = "finances.manage", "Record charges, payments, expenses and dues"
    ANNOUNCEMENTS_MANAGE = "announcements.manage", "Publish club announcements and news"
    TRAINING_MANAGE = "training.manage", "Plan training sessions and coaching groups"
    WELFARE_MANAGE = "welfare.manage", "Run welfare projects"
    ACTIVITIES_MANAGE = "activities.manage", "Plan club activities such as nights out"
    GOVERNANCE_MANAGE = "governance.manage", "Set the committee, nominate representatives and run meetings"


ALL_PERMISSIONS: frozenset[str] = frozenset(Permission.values)


class RoleKey(models.TextChoices):
    """Template roles every organization starts with. Custom roles have no key."""

    ADMIN = "admin"
    CAPTAIN = "captain"
    ASSISTANT_CAPTAIN = "assistant_captain"
    COMMITTEE = "committee"
    REFEREE = "referee"
    MEMBER = "member"


P = Permission
# Starting permissions for each template. Organizations can edit all but Admin afterwards.
ROLE_TEMPLATES: list[tuple[str, str, frozenset[str]]] = [
    (RoleKey.ADMIN, "Admin", ALL_PERMISSIONS),
    (
        RoleKey.CAPTAIN,
        "Captain",
        frozenset(
            {
                P.MEMBERS_MANAGE,
                P.COMPETITIONS_MANAGE,
                P.RESULTS_MANAGE,
                P.SCORING_ASSIGNED,
                P.ANNOUNCEMENTS_MANAGE,
                P.TRAINING_MANAGE,
                P.ACTIVITIES_MANAGE,
            }
        ),
    ),
    (
        RoleKey.ASSISTANT_CAPTAIN,
        "Assistant captain",
        frozenset({P.COMPETITIONS_MANAGE, P.SCORING_ASSIGNED, P.TRAINING_MANAGE, P.ACTIVITIES_MANAGE}),
    ),
    (
        RoleKey.COMMITTEE,
        "Committee",
        frozenset(
            {
                P.FINANCES_VIEW,
                P.FINANCES_MANAGE,
                P.WELFARE_MANAGE,
                P.ANNOUNCEMENTS_MANAGE,
                P.ACTIVITIES_MANAGE,
            }
        ),
    ),
    # The referee decides matches that aren't played to a finish (decision D5, 2026-11-21).
    (RoleKey.REFEREE, "Referee", frozenset({P.RESULTS_REFEREE, P.RESULTS_MANAGE, P.SCORING_ASSIGNED})),
    (RoleKey.MEMBER, "Member", frozenset()),
]
