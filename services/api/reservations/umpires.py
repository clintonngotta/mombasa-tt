"""Tournament umpires and table umpires (user request, 2026-11-22).

Competition staff pick who umpires at a tournament: members of the host, and players entered in it so
they can umpire when they have no match. Each table can have one of them for the whole tournament:
every match sent to that table takes the table's umpire at once, so the umpire is set before the
players arrive. Staff change a table's umpire at any time; a match already being scored keeps its own.

A table umpire is never forced on a match. Someone playing in that match, or playing elsewhere at that
moment, is skipped and the match waits for staff to choose, as it did before table umpires existed.
"""

from django.db import transaction
from django.db.models import Q

from accounts.models import User
from competitions import matchday
from competitions.models import Entry, EntryPlayer, Match, Rubber, Tournament
from core.exceptions import ApiException
from facilities.models import Table
from organizations.models import Membership

from .models import Hold, Reservation, TableUmpire, TournamentUmpire

NOT_STARTED = "not_started"


def eligible(tournament: Tournament):
    """Who staff may put on the umpires: active members of the host and players with an accepted entry.
    A guest nobody has claimed can't sign in, so can't score."""
    members = Membership.objects.active().filter(organization_id=tournament.organization_id).values("user_id")
    entrants = EntryPlayer.objects.filter(
        event__tournament=tournament, entry__status=Entry.Status.ACCEPTED
    ).values("user_id")
    unclaimed_guest = Q(guest__isnull=False, guest__claimed_by__isnull=True)
    return (
        User.objects.filter(is_active=True)
        .filter(Q(id__in=members) | Q(id__in=entrants))
        .exclude(unclaimed_guest)
    )


def roster(tournament: Tournament) -> list[dict]:
    """The tournament's umpires with their table and what they are doing now."""
    listed = list(TournamentUmpire.objects.filter(tournament=tournament).select_related("user"))
    people = [entry.user_id for entry in listed]
    tables = {
        assigned.umpire_id: assigned.table
        for assigned in TableUmpire.objects.filter(tournament=tournament).select_related("table")
    }
    playing = {
        hold.user_id: hold.reservation.table.label
        for hold in Hold.objects.filter(user_id__in=people, active=True).select_related("reservation__table")
    }
    entered = set(
        EntryPlayer.objects.filter(
            event__tournament=tournament, entry__status=Entry.Status.ACCEPTED, user_id__in=people
        ).values_list("user_id", flat=True)
    )
    return [
        {
            "user_id": entry.user_id,
            "display_name": entry.user.display_name,
            "table_id": tables[entry.user_id].id if entry.user_id in tables else None,
            "table": tables[entry.user_id].label if entry.user_id in tables else "",
            "playing_on": playing.get(entry.user_id, ""),
            "entered": entry.user_id in entered,
        }
        for entry in sorted(listed, key=lambda entry: entry.user.display_name.lower())
    ]


def add(tournament: Tournament, user: User, actor) -> None:
    if not eligible(tournament).filter(pk=user.pk).exists():
        raise ApiException(
            "not_eligible",
            "Only members of the host and players entered in this tournament can umpire here.",
            409,
        )
    _, created = TournamentUmpire.objects.get_or_create(
        tournament=tournament, user=user, defaults={"added_by": actor}
    )
    if created:
        matchday.log(tournament, matchday.Action.UMPIRE_LISTED, user.display_name, actor=actor)


def remove(tournament: Tournament, user: User, actor) -> None:
    """Off the umpires and off their table. Matches given to them that nobody has started scoring are
    taken back unless their role still lets them score; one in play stays theirs until staff decide."""
    from scoring import service as scoring
    from scoring.models import Scorecard

    found = TournamentUmpire.objects.filter(tournament=tournament, user=user).first()
    if found is None:
        return
    TableUmpire.objects.filter(tournament=tournament, umpire=user).delete()
    found.delete()
    cards = (
        Scorecard.objects.filter(umpire=user, confirmed_at__isnull=True, revision=0)
        .filter(
            Q(match__draw__event__tournament=tournament)
            | Q(rubber__match__draw__event__tournament=tournament)
        )
        .select_related("match__draw__event__tournament", "rubber__match__draw__event__tournament")
    )
    for card in cards:
        match = card.match or card.rubber.match
        if scoring.can_umpire(user, match.draw.event):
            continue
        scoring.assign(match, card.rubber, None, actor)
    matchday.log(tournament, matchday.Action.UMPIRE_UNLISTED, user.display_name, actor=actor)


def umpire_of_table(tournament: Tournament, table: Table):
    found = TableUmpire.objects.filter(tournament=tournament, table=table).select_related("umpire").first()
    return found.umpire if found else None


def set_table(tournament: Tournament, table: Table, user: User | None, actor) -> None:
    """Give the table an umpire, or none. Someone already on another table moves to this one. The match
    waiting on the table, if nobody has started scoring it, takes the new umpire too."""
    from scoring import service as scoring

    if user is None:
        TableUmpire.objects.filter(tournament=tournament, table=table).delete()
        matchday.log(
            tournament,
            matchday.Action.TABLE_UMPIRE,
            f"{table.label}: no table umpire",
            actor=actor,
            table=table,
        )
        return
    if not TournamentUmpire.objects.filter(tournament=tournament, user=user).exists():
        raise ApiException("not_listed", "Add them to the tournament's umpires first.", 409)
    before = umpire_of_table(tournament, table)
    TableUmpire.objects.filter(tournament=tournament, umpire=user).exclude(table=table).delete()
    TableUmpire.objects.update_or_create(
        tournament=tournament, table=table, defaults={"umpire": user, "assigned_by": actor}
    )
    matchday.log(
        tournament,
        matchday.Action.TABLE_UMPIRE,
        f"{table.label}: {user.display_name}",
        actor=actor,
        table=table,
    )
    _follow_on_held(tournament, table, before, user, actor)
    waiting = (
        Reservation.objects.filter(
            table=table, status=Reservation.Status.ACTIVE, match__draw__event__tournament=tournament
        )
        .select_related("match__draw__event__tournament", "match__entry_a", "match__entry_b")
        .first()
    )
    if waiting is None:
        return
    match = waiting.match
    rubber = _current_rubber(match)
    card = _card(match, rubber)
    if card is not None and (card.revision > 0 or card.umpire_id == user.id):
        return  # being scored: it keeps its umpire
    try:
        with transaction.atomic():
            scoring.assign(match, rubber, user, actor)
    except ApiException:
        return  # they play in it, or are playing now: staff choose for this match


def _follow_on_held(tournament: Tournament, table: Table, before, user: User, actor) -> None:
    """Matches waiting in the queue for this table (TASK-153) take its new umpire, unless somebody has
    started scoring them or staff gave them someone other than the table's old umpire."""
    from scoring import service as scoring

    held = Match.objects.filter(
        held_table=table,
        draw__event__tournament=tournament,
        status=Match.Status.SCHEDULED,
        dispatched_at__isnull=True,
    ).select_related("draw__event__tournament", "entry_a", "entry_b")
    for match in held:
        rubber = _current_rubber(match)
        card = _card(match, rubber)
        if card is not None and (
            card.revision > 0 or card.umpire_id not in (None, getattr(before, "id", None))
        ):
            continue
        if card is not None and card.umpire_id == user.id:
            continue
        try:
            with transaction.atomic():
                scoring.assign(match, rubber, user, actor)
        except ApiException:
            continue  # they play in it, or are playing now: staff choose for this match


def _current_rubber(match: Match) -> Rubber | None:
    from . import service

    return service.current_rubber(match) if match.draw.event.is_team else None


def _card(match: Match, rubber: Rubber | None):
    from scoring.models import Scorecard

    return Scorecard.objects.filter(**({"rubber": rubber} if rubber else {"match": match})).first()


def take_table_umpire(match: Match, rubber: Rubber | None, table: Table, actor) -> None:
    """A match (or the next rubber of a tie) has just gone to a table: it takes the table's umpire unless
    it already has one or the table umpire can't take it now. Never refuses the dispatch."""
    from scoring import service as scoring

    tournament = match.draw.event.tournament
    umpire = umpire_of_table(tournament, table)
    if umpire is None:
        return
    card = _card(match, rubber)
    if card is not None and card.umpire_id is not None:
        return
    try:
        with transaction.atomic():
            scoring.assign(match, rubber, umpire, actor)
    except ApiException:
        return  # playing in it, or playing elsewhere right now
    where = f" (rubber {rubber.position})" if rubber else ""
    matchday.log(
        tournament,
        matchday.Action.UMPIRE_ASSIGNED,
        f"{matchday.match_title(match)}{where}: {umpire.display_name}, {table.label}'s umpire",
        actor=actor,
        match=match,
        table=table,
    )
