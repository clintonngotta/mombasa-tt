"""A player who leaves part-way is replaced by someone else (TASK-155, user request 2026-11-28).

The place carries on (user decision, 2026-11-28): whoever comes in plays the matches the entry has
left, and the results it already has (group points, knockout progress) stay with the place. The matches
already played stay with the people who played them, because ratings, recaps and players' records read
a match's players from its entries.

So a singles or doubles entry is never edited: a new entry with the newcomer (and, in doubles, the
partner who stays) takes the old one's place in the draw and in every match still to play, and the old
one is marked `replaced`, pointing at it. Group tables count both as one member (`carried`). A team's
roster changes in place instead: each rubber already keeps who played it, so the team's past is safe.
"""

from django.db.models import Q
from django.utils import timezone

from core.exceptions import ApiException

from .models import DrawPlace, DrawVersion, Entry, EntryPlayer, Event, Lineup, Match, Rubber, Tournament

S = Entry.Status


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def current(entry: Entry | None) -> Entry | None:
    """The entry that holds this one's place now: itself, or whoever replaced it (and so on)."""
    seen = set()
    while entry is not None and entry.replaced_by_id is not None and entry.id not in seen:
        seen.add(entry.id)
        entry = entry.replaced_by
    return entry


def carried(event: Event) -> dict[str, str]:
    """Entries of the event that were replaced, as {old id: id of the entry holding the place now}."""
    links = dict(
        Entry.objects.filter(event=event, status=S.REPLACED, replaced_by__isnull=False).values_list(
            "id", "replaced_by_id"
        )
    )
    found = {}
    for old in links:
        now = links[old]
        while now in links:
            now = links[now]
        found[str(old)] = str(now)
    return found


def _ensure_free_to_swap(entry: Entry, leaving) -> None:
    """Nothing of the entry is being played right now: a match on a table, being scored, or (for a team)
    a lineup naming the player who leaves for a tie still to come."""
    from scoring.models import Scorecard  # scoring builds on competitions

    left = Match.objects.filter(
        draw__event=entry.event, draw__status=DrawVersion.Status.PUBLISHED, status=Match.Status.SCHEDULED
    ).filter(Q(entry_a=entry) | Q(entry_b=entry))
    for match in left:
        scored = Scorecard.objects.filter(Q(match=match) | Q(rubber__match=match), revision__gt=0).exists()
        begun = match.rubbers.exclude(status=Rubber.Status.SCHEDULED).exists()
        if match.dispatched_at is not None or scored or begun:
            raise _conflict(
                "match_in_play",
                "One of this entry's matches is being played. Swap the player once it is decided, or "
                "call it back from its table first.",
            )
    named = str(leaving.id)
    lineups = Lineup.objects.filter(match__in=left, entry=entry).values_list("picks", flat=True)
    if any(named in rubber for picks in lineups for rubber in picks):
        raise _conflict(
            "in_lineup",
            "The player who leaves is in a lineup the team handed in. Reset that lineup first.",
        )


def substitute(entry: Entry, leaving, joining, actor, reason: str = "") -> Entry:
    """`joining` plays in place of `leaving` from now on. Returns the entry that holds the place:
    the same one for a team, a new one for singles and doubles. Call with the tournament locked."""
    event = entry.event
    tournament = event.tournament
    if tournament.status == Tournament.Status.DRAFT or tournament.is_closed or event.is_closed:
        raise _conflict("event_closed", "Players can be swapped only while the event can still be played.")
    if event.kind == Event.Kind.JUMBLES:
        raise _conflict(
            "not_for_jumbles", "In Jumbles partners change every round; enter the new player instead."
        )
    if entry.status != S.ACCEPTED:
        raise _conflict("not_accepted", "Only an entry that holds a place can take a new player.")
    seats = list(entry.players.select_related("user").order_by("position"))
    leaving_seat = next((seat for seat in seats if seat.user_id == leaving.id), None)
    if leaving_seat is None:
        raise _conflict("not_in_entry", "That player isn't part of this entry.")
    if any(seat.user_id == joining.id for seat in seats):
        raise _conflict("already_in_entry", "The new player is already part of this entry.")
    if EntryPlayer.objects.filter(event=event, live=True, user=joining).exists():
        raise _conflict("already_entered", f"{joining.display_name} is already entered in this event.")
    _ensure_free_to_swap(entry, leaving)

    if event.is_team:
        leaving_seat.user = joining
        leaving_seat.checked_in_at = None
        leaving_seat.save(update_fields=["user", "checked_in_at"])
        if entry.captain_id == leaving.id:
            entry.captain = joining
            entry.save(update_fields=["captain"])
        return entry

    now = timezone.now()
    # The old entry stops standing first, so the partner who stays can stand in the new one.
    entry.status = S.REPLACED
    entry.reason = reason
    entry.save(update_fields=["status", "reason"])
    entry.players.update(live=False)
    taking = Entry.objects.create(
        event=event,
        status=S.ACCEPTED,
        entered_by=actor,
        decided_at=now,
        decided_by=actor,
        # Someone swapped in at the desk is there to play.
        checked_in_at=now if entry.checked_in_at else None,
        checked_in_by=actor if entry.checked_in_at else None,
    )
    EntryPlayer.objects.bulk_create(
        EntryPlayer(
            entry=taking,
            event=event,
            user=joining if seat is leaving_seat else seat.user,
            position=seat.position,
            checked_in_at=None if seat is leaving_seat else seat.checked_in_at,
        )
        for seat in seats
    )
    entry.replaced_by = taking
    entry.save(update_fields=["replaced_by"])

    # The place in the draw, and every match still to play, go to the new entry. Decided matches
    # stay as they were played; a bye still to pass on is part of what is left.
    drawn = ~Q(draw__status=DrawVersion.Status.SUPERSEDED)
    DrawPlace.objects.filter(drawn, entry=entry).update(entry=taking)
    open_matches = Match.objects.filter(drawn, draw__event=event).filter(
        Q(status=Match.Status.SCHEDULED) | Q(status=Match.Status.BYE, winner__isnull=True)
    )
    open_matches.filter(entry_a=entry).update(entry_a=taking)
    open_matches.filter(entry_b=entry).update(entry_b=taking)
    return taking
