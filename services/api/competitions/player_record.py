"""One player in one tournament (TASK-148): who they are, as far as their profile lets others see, and
what they did there: the events they entered, their seed and group, every match of the published draws
they played or are due to play, and what each event has decided about them so far.

Nothing here is new to the reader: entries, draws, matches and standings are already public on the
tournament's pages. This gathers one player's part of them. The profile follows the player page's own
rule (REQ-006): signed-in readers see a listed player's card and published details, everyone else the
name alone, so the answer never tells a visitor who joined the directory.
"""

from profiles.models import PlayerProfile
from profiles.serializers import PlayerSerializer, SignedOutPlayerSerializer
from profiles.views import listed_players

from . import drawing
from .models import DrawVersion, Entry, Event, Match, Tournament

# A tournament holds at most MAX_EVENTS events, so this bounds the entries one player can have
# (their own entry and, in Jumbles, a pairing for every round).
MAX_ENTRIES = 200


def _profile(player, viewer) -> tuple[dict, bool]:
    """What the reader may see of the player, and whether the player page exists for them."""
    if viewer.is_authenticated:
        listed = listed_players().filter(user=player).first()
        if listed is not None:
            return PlayerSerializer(listed).data, True
    return SignedOutPlayerSerializer(PlayerProfile(user=player)).data, False


def _result(match: Match, mine: set) -> str:
    if match.status != Match.Status.COMPLETED or not match.winner_id:
        return ""
    return "won" if match.winner_id in mine else "lost"


def record(tournament: Tournament, player, viewer, staff: bool) -> dict | None:
    """The player's record in the tournament, or None when they have no part in it the reader may see.

    Readers see an entry once it is accepted, or once it sits in a published draw (a player who
    withdrew after the draw keeps the matches they played). Staff and the player themselves see every
    entry, as on the entries list."""
    entries = list(
        Entry.objects.filter(event__tournament=tournament, players__user=player)
        .select_related("event")
        .prefetch_related("players__user")
        .order_by("event__position", "event__created_at", "created_at")[:MAX_ENTRIES]
    )
    if not entries:
        return None
    draws = {
        draw.event_id: draw
        for draw in DrawVersion.objects.filter(
            event_id__in={entry.event_id for entry in entries}, status=DrawVersion.Status.PUBLISHED
        ).select_related("event__tournament")
    }
    everything = staff or (viewer.is_authenticated and viewer.pk == player.pk)

    events = []
    won = lost = 0
    for event in sorted({entry.event for entry in entries}, key=lambda e: (e.position, e.created_at)):
        of_event = [entry for entry in entries if entry.event_id == event.id]
        own = next((e for e in of_event if e.status != Entry.Status.PAIRING), None)
        mine = {entry.id for entry in of_event}
        draw = draws.get(event.id)
        shown = _in_draw(draw, own, mine, event, staff) if draw else None
        if own is None or not (
            everything or own.status == Entry.Status.ACCEPTED or (shown and shown["in_draw"])
        ):
            continue
        matches = shown["matches"] if shown else []
        event_won = sum(1 for m in matches if m["result"] == "won")
        event_lost = sum(1 for m in matches if m["result"] == "lost")
        won, lost = won + event_won, lost + event_lost
        events.append(
            {
                "event": event,
                "entry": own,
                "seed": shown["seed"] if shown else None,
                "group_name": shown["group_name"] if shown else "",
                "group_rank": shown["group_rank"] if shown else None,
                "placement": shown["placement"] if shown else "",
                "won": event_won,
                "lost": event_lost,
                "matches": matches,
            }
        )
    if not events:
        return None
    profile, page = _profile(player, viewer)
    return {
        "player": profile,
        "has_player_page": page,
        "won": won,
        "lost": lost,
        "events": events,
    }


def _in_draw(draw: DrawVersion, own: Entry | None, mine: set, event: Event, staff: bool) -> dict:
    """The player's place in a published draw: seed, group, rank, placement and their matches."""
    places = list(draw.places.select_related("entry").prefetch_related("entry__players__user"))
    place = next((p for p in places if own and p.entry_id == own.id), None)
    matches = drawing._matches_of(draw)
    shown = drawing._match_describer(
        matches,
        drawing._entries_of(draw, places),
        {p.entry_id: p.seed for p in places},
        event.status == Event.Status.IN_PROGRESS,
        drawing._times_shown(draw, staff),
        event,
    )
    theirs = [
        {**shown(match), "side": "a" if match.entry_a_id in mine else "b", "result": _result(match, mine)}
        for match in matches
        if match.entry_a_id in mine or match.entry_b_id in mine
    ]
    multiple = len({p.group for p in places if p.group}) > 1
    group_rank = None
    if event.kind == Event.Kind.JUMBLES or (place and place.group):
        rows, _ = drawing.group_table(draw, place.group if place else 0)
        row = next((r for r in rows if own and r.member == str(own.id)), None)
        group_rank = row.rank if row else None
    decided = next(
        (
            found["label"]
            for found in drawing.placements(draw)
            if own and str(own.id) in {str(pk) for pk in found["entry_ids"]}
        ),
        "",
    )
    return {
        "in_draw": place is not None or bool(theirs),
        "seed": place.seed if place else None,
        "group_name": drawing.group_name(place.group) if place and place.group and multiple else "",
        "group_rank": group_rank,
        "placement": decided,
        "matches": theirs,
    }
