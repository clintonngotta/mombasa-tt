"""The final results sheet of a tournament: for each finished event, its podium (first, second and the
joint thirds, as the award ceremony has them) with each player's club, as a branded PDF to print and a
PNG to share.

A player's club is the club or team they are an active member of (the earliest they joined, if several).
A player without one is shown with a dash.
"""

from dataclasses import dataclass, field
from datetime import date

from core import brand, pdf
from organizations.models import Membership, Organization

from . import ceremony
from .models import Entry, Event, Tournament
from .serializers import organizer

CLUB_KINDS = (Organization.Kind.CLUB, Organization.Kind.TEAM, Organization.Kind.CLUB_FACILITY)
NO_CLUB = "—"


@dataclass
class Placing:
    place: int
    names: str
    club: str


@dataclass
class EventResult:
    name: str
    finished: bool
    column: str = "Player name"  # "Players" for pairs, "Team" for teams
    placings: list[Placing] = field(default_factory=list)


def dates(starts: date, ends: date) -> str:
    """ "28 November 2026", "28–29 November 2026" or "30 November – 1 December 2026"."""
    if starts == ends:
        return f"{starts.day} {starts:%B %Y}"
    if (starts.year, starts.month) == (ends.year, ends.month):
        return f"{starts.day}–{ends.day} {ends:%B %Y}"
    if starts.year == ends.year:
        return f"{starts.day} {starts:%B} – {ends.day} {ends:%B %Y}"
    return f"{starts.day} {starts:%B %Y} – {ends.day} {ends:%B %Y}"


def where_and_when(tournament: Tournament) -> str:
    venue = tournament.venue
    place = f"{venue.name}, {venue.town}" if venue else ""
    return " · ".join(part for part in (dates(tournament.starts_on, tournament.ends_on), place) if part)


def results(tournament: Tournament) -> list[EventResult]:
    """Every event that isn't cancelled, in the programme's order, with the podium of each finished one.
    Names and clubs in two queries."""
    events = list(tournament.events.exclude(status=Event.Status.CANCELLED).order_by("position", "created_at"))
    podiums = {event.id: ceremony.podium(event) for event in events}
    ids = {entry for places in podiums.values() for _, entries in places for entry in entries}
    entries = {
        entry.id: entry for entry in Entry.objects.filter(id__in=ids).prefetch_related("players__user")
    }
    users = {place.user_id for entry in entries.values() for place in entry.players.all()}
    clubs: dict = {}
    for membership in (
        Membership.objects.active()
        .filter(user_id__in=users, organization__kind__in=CLUB_KINDS)
        .select_related("organization")
        .order_by("joined_at")
    ):
        clubs.setdefault(membership.user_id, membership.organization.name)

    found = []
    for event in events:
        row = EventResult(event.name, finished=bool(podiums[event.id]))
        for place, entry_ids in podiums[event.id]:
            for entry_id in entry_ids:
                entry = entries.get(entry_id)
                if entry is None:
                    continue
                players = list(entry.players.all())
                if entry.team_name:
                    row.column = "Team"
                elif len(players) > 1:
                    row.column = "Players"
                names = entry.team_name or " / ".join(p.user.display_name for p in players)
                own = list(dict.fromkeys(clubs[p.user_id] for p in players if p.user_id in clubs))
                row.placings.append(Placing(place, names, " / ".join(own) or NO_CLUB))
        found.append(row)
    return found


def as_pdf(tournament: Tournament) -> bytes:
    found = results(tournament)
    blocks: list = []
    for event in found:
        if event.finished:
            blocks.append(
                pdf.Table(
                    ["Rank", event.column, "Club / residence"],
                    [[str(p.place), p.names, p.club] for p in event.placings],
                    widths=[0.6, 3, 2.4],
                    ranked=True,
                    title=event.name,
                )
            )
    playing = [event.name for event in found if not event.finished]
    if playing:
        blocks.append(pdf.Text(f"Still being played: {', '.join(playing)}.", muted=True))
    if not blocks:
        blocks.append(pdf.Text("This tournament has no events yet.", muted=True))
    return pdf.document(
        f"Final results: {tournament.name}",
        where_and_when(tournament),
        blocks,
        prepared_by=organizer(tournament)["name"],
    )


def as_image(tournament: Tournament) -> bytes:
    found = results(tournament)
    cards = [
        brand.Card(
            event.name,
            [brand.Row(p.names, p.club, badge=p.place, strong=p.place == 1) for p in event.placings],
        )
        for event in found
        if event.finished
    ]
    playing = len([event for event in found if not event.finished])
    if not cards:
        cards = [brand.Card("Results", [brand.Row("No event has finished yet.", note=True)])]
    return brand.share_image(
        f"Final results: {tournament.name}",
        where_and_when(tournament),
        cards,
        footnote=f"{playing} more event{'s' if playing != 1 else ''} still being played." if playing else "",
    )
