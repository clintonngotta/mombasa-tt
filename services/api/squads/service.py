"""Who can be picked, the rotation the app recommends, and picking (REQ-050)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Max

from core.exceptions import ApiException
from organizations.models import Membership, Organization
from organizations.representatives import CLUB_KINDS
from ratings.elo import START
from ratings.models import Rating

from .models import Squad, SquadPlace

MAX_CANDIDATES = 300
User = get_user_model()


def eligible(organization: Organization) -> dict:
    """{user id: club or None}: who the organization may pick. A club picks its active members; a
    regional body picks the active members of its region's clubs (and each comes with their club)."""
    if organization.kind == Organization.Kind.REGIONAL_BODY:
        clubs = Organization.objects.filter(
            country=organization.country, region__iexact=organization.region, kind__in=CLUB_KINDS
        )
        rows = (
            Membership.objects.active()
            .filter(organization__in=clubs, user__is_active=True)
            .select_related("organization")
            .order_by("joined_at")
        )
        found: dict = {}
        for membership in rows:
            found.setdefault(membership.user_id, membership.organization)
        return found
    members = Membership.objects.active().filter(organization=organization, user__is_active=True)
    return dict.fromkeys(members.values_list("user_id", flat=True))


def previous_squad(squad: Squad) -> Squad | None:
    """The organization's squad before this one: the latest published one that starts earlier."""
    return (
        Squad.objects.filter(
            organization=squad.organization_id, status=Squad.Status.PUBLISHED, starts_on__lt=squad.starts_on
        )
        .exclude(pk=squad.pk)
        .order_by("-starts_on", "-created_at")
        .first()
    )


def recommendation(squad: Squad) -> list[dict]:
    """Everyone the app would pick next, in rotation: those who represented least recently first (never
    comes before ever), then the higher rating in the squad's discipline; whoever was in the previous
    squad goes last."""
    people = eligible(squad.organization)
    # Not those already in, nor those who declined this squad: they said they can't go.
    out = (*SquadPlace.OPEN, SquadPlace.Status.DECLINED)
    taken = set(squad.places.filter(status__in=out).values_list("user_id", flat=True))
    candidates = [pk for pk in people if pk not in taken]
    represented = dict(
        SquadPlace.objects.filter(
            squad__organization=squad.organization_id,
            squad__status=Squad.Status.PUBLISHED,
            squad__starts_on__lt=squad.starts_on,
            status=SquadPlace.Status.ACCEPTED,
            user__in=candidates,
        )
        .values("user")
        .annotate(last=Max("squad__starts_on"))
        .values_list("user", "last")
    )
    before = previous_squad(squad)
    in_last = (
        set(before.places.filter(status=SquadPlace.Status.ACCEPTED).values_list("user_id", flat=True))
        if before
        else set()
    )
    ratings = dict(
        Rating.objects.filter(user__in=candidates, discipline=squad.discipline).values_list("user", "rating")
    )
    names = dict(User.objects.filter(pk__in=candidates).values_list("pk", "display_name"))
    rows = [
        {
            "user_id": pk,
            "display_name": names.get(pk, ""),
            "club": people[pk].name if people[pk] else None,
            "last_represented_on": represented.get(pk),
            "in_previous_squad": pk in in_last,
            "rating": round(ratings.get(pk, START)),
        }
        for pk in candidates
    ]
    rows.sort(
        key=lambda row: (
            row["in_previous_squad"],
            row["last_represented_on"] or date.min,
            -row["rating"],
            row["display_name"].lower(),
        )
    )
    return rows[:MAX_CANDIDATES]


def free_places(squad: Squad, slot_id: str) -> int:
    slot = next((slot for slot in squad.slots if slot["id"] == slot_id), None)
    if slot is None:
        raise ApiException("no_such_slot", "This squad has no such slot.", 400)
    held = squad.places.filter(slot=slot_id, status__in=SquadPlace.OPEN).count()
    return slot["places"] - held


def pick(squad: Squad, actor, *, user_id, slot: str, reason: str) -> SquadPlace:
    """Put a player in a slot. Call with the squad locked. Someone the rotation doesn't put among the
    next players for the places still free needs a reason."""
    people = eligible(squad.organization)
    if user_id not in people:
        raise ApiException("not_eligible", "Pick an active member.", 400)
    free = free_places(squad, slot)
    if free <= 0:
        raise ApiException("slot_full", "Every place in this slot is taken.", 409)
    if squad.places.filter(user_id=user_id, status__in=SquadPlace.OPEN).exists():
        raise ApiException("already_picked", "They already have a place in this squad.", 409)
    first = {row["user_id"] for row in recommendation(squad)[:free]}
    recommended = user_id in first
    if not recommended and not reason:
        raise ApiException(
            "reason_required",
            "The rotation puts other players first. Say why you are picking this one.",
            400,
        )
    return SquadPlace.objects.create(
        squad=squad,
        slot=slot,
        user_id=user_id,
        club=people[user_id],
        recommended=recommended,
        override_reason="" if recommended else reason,
        picked_by=actor,
    )
