"""Team ties (REQ-011): lineups, rubbers played one at a time, and the tie decided by the wins needed.

A tie is a draw match of a team event. Each team hands in a lineup: for every rubber of the event's tie
template, the one or two players it sends out. A lineup is the team's own until both are in; then the
tie begins and its rubbers are made. Rubbers are decided in order. The moment a team has the wins it
needs, the rubbers left are marked not played (they are never scored and never rated) and the tie is
decided like any other match of the draw.

Callers hold the tournament row lock, like every other change to a tournament.
"""

from core.exceptions import ApiException

from . import drawing, signals, standings
from .models import DrawVersion, Entry, Event, Lineup, Match, Rubber, RubberPlayer

R = Rubber.Status
# What a lineup was made for: changing any of these under a handed-in lineup would leave it wrong.
LINEUP_FIELDS = {"kind", "best_of", "tie_rubbers", "tie_wins_needed"}


def has_lineups(event: Event) -> bool:
    return Lineup.objects.filter(match__draw__event=event).exists()


SIZE = {Rubber.Kind.SINGLES: 1, Rubber.Kind.DOUBLES: 2}


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def _invalid(message: str) -> ApiException:
    return ApiException("invalid_lineup", message, 400)


def ensure_lineups_open(match: Match) -> None:
    """Lineups are handed in for a tie of the published draw whose two teams are known, until it begins."""
    event = match.draw.event
    if not event.is_team:
        raise _conflict("not_a_tie", "Only matches of a team event have lineups.")
    if match.draw.status != DrawVersion.Status.PUBLISHED:
        raise _conflict("draw_not_published", "Only ties of the published draw are played.")
    if event.is_closed or event.tournament.is_closed:
        raise _conflict("event_closed", "This event is over, so its lineups can't change.")
    if match.status != Match.Status.SCHEDULED:
        raise _conflict("match_decided", "This tie is already decided.")
    if match.entry_a_id is None or match.entry_b_id is None:
        raise _conflict("match_not_ready", "Both teams of this tie aren't known yet.")
    if match.rubbers.exists():
        raise _conflict("tie_begun", "Both lineups are in and the tie has begun, so they can't change.")


def lineup_problem(event: Event, entry: Entry, picks: list[list[str]]) -> str:
    """Why these picks can't be the team's lineup, or an empty string. A player may play several
    rubbers; the two players of a doubles are different people; everybody is on the team's roster."""
    template = event.tie_rubbers
    if len(picks) != len(template):
        return f"A tie has {len(template)} rubbers: name the players for each one."
    roster = {str(pk) for pk in entry.players.values_list("user_id", flat=True)}
    for number, (kind, players) in enumerate(zip(template, picks, strict=True), start=1):
        if len(players) != SIZE[kind]:
            wanted = "one player" if kind == Rubber.Kind.SINGLES else "two players"
            return f"Rubber {number} is a {kind}: it takes {wanted}."
        if len(set(players)) != len(players):
            return f"Rubber {number} is a doubles: its two players are different people."
        if not set(players) <= roster:
            return f"Rubber {number} names a player who isn't on the team's roster."
    return ""


def submit_lineup(match: Match, entry: Entry, actor, picks: list[list[str]]) -> Lineup:
    """Hand in (or replace) a team's lineup. When the other team's is in too, the tie begins."""
    ensure_lineups_open(match)
    if entry.id not in (match.entry_a_id, match.entry_b_id):
        raise _conflict("not_in_match", "That team doesn't play in this tie.")
    problem = lineup_problem(match.draw.event, entry, picks)
    if problem:
        raise _invalid(problem)
    lineup, _ = Lineup.objects.update_or_create(
        match=match, entry=entry, defaults={"picks": picks, "submitted_by": actor}
    )
    _begin_if_ready(match)
    return lineup


def _begin_if_ready(match: Match) -> None:
    lineups = {lineup.entry_id: lineup for lineup in match.lineups.all()}
    if len(lineups) < 2:
        return
    sides = (
        (RubberPlayer.Side.A, lineups[match.entry_a_id]),
        (RubberPlayer.Side.B, lineups[match.entry_b_id]),
    )
    for index, kind in enumerate(match.draw.event.tie_rubbers):
        rubber = Rubber.objects.create(match=match, position=index + 1, kind=kind)
        RubberPlayer.objects.bulk_create(
            RubberPlayer(rubber=rubber, side=side, user_id=user_id, position=position)
            for side, lineup in sides
            for position, user_id in enumerate(lineup.picks[index])
        )


def reset_lineups(match: Match) -> None:
    """Staff send both teams back to choose again, as long as no rubber has been decided."""
    event = match.draw.event
    if event.is_closed or event.tournament.is_closed:
        raise _conflict("event_closed", "This event is over, so its lineups can't change.")
    if match.rubbers.exclude(status=R.SCHEDULED).exists() or match.status != Match.Status.SCHEDULED:
        raise _conflict("tie_under_way", "A rubber of this tie is already decided, so its lineups stand.")
    # A rubber being scored would lose its sheet with the rubber (scoring.Scorecard, by its related name).
    being_scored = match.rubbers.filter(scorecard__revision__gt=0).exists()
    # A device's report about a rubber is kept with the rubber's sheet: it must outlive a reset too.
    if being_scored or match.rubbers.filter(scorecard__conflicts__isnull=False).exists():
        raise _conflict("tie_under_way", "A rubber of this tie is being scored, so its lineups stand.")
    if match.dispatched_at is not None:
        # Its players are held rubber by rubber; new lineups would leave the tie out there without them.
        raise _conflict("tie_on_table", "This tie is on a table. Call it back before its lineups change.")
    match.rubbers.all().delete()
    match.lineups.all().delete()


tie_score = drawing.tie_score


def record_rubber(rubber: Rubber, winner: Entry, *, outcome: str = Match.Outcome.PLAYED, games=()) -> None:
    """A rubber is decided. Only the next rubber in order can be: one is played at a time. `games` are
    [a, b] points in playing order, a being the tie's side a. Who may decide a rubber arrives with
    scoring; this is what follows from the result."""
    match = rubber.match
    if match.draw.status != DrawVersion.Status.PUBLISHED:
        raise _conflict("draw_not_published", "Only ties of the published draw are played.")
    if match.status != Match.Status.SCHEDULED or rubber.status != R.SCHEDULED:
        raise _conflict("rubber_closed", "This rubber is already decided or was not needed.")
    current = match.rubbers.filter(status=R.SCHEDULED).order_by("position").first()
    if current.id != rubber.id:
        raise _conflict(
            "rubber_out_of_turn",
            f"Rubber {current.position} is played first: a tie plays one rubber at a time.",
        )
    if winner.id not in (match.entry_a_id, match.entry_b_id):
        raise _conflict("not_in_match", "The winner is one of the two teams of the tie.")
    games = [list(game) for game in games]
    drawing.check_games(match.draw.event.best_of, games, outcome, a_won=winner.id == match.entry_a_id)
    rubber.winner = winner
    rubber.status = R.COMPLETED
    rubber.outcome = outcome
    rubber.games = games
    rubber.save(update_fields=["winner", "status", "outcome", "games"])
    decided = max(tie_score(match)) >= match.draw.event.tie_wins_needed
    signals.rubber_decided.send(sender=Rubber, rubber=rubber, tie_decided=decided)
    if decided:
        # Decided: the tie goes on through the draw like any match, and what is left is not played.
        drawing.record_result(match, winner)


def result_of(match: Match) -> standings.Result:
    """A decided tie as the group table counts it: individual matches won and lost, and the games and
    points of every rubber that was played (3.7.5.2)."""
    a_won = match.winner_id == match.entry_a_id
    loser = match.entry_b_id if a_won else match.entry_a_id
    event = match.draw.event
    games: list[tuple[int, int]] = []
    won = lost = 0
    for rubber in match.rubbers.all():
        if rubber.status != R.COMPLETED:
            continue
        mine = rubber.winner_id == match.winner_id
        won += mine
        lost += not mine
        # From the rubber's winner first, completed in their favour if it wasn't finished; then turned
        # to the tie winner's side.
        rubber_a_won = rubber.winner_id == match.entry_a_id
        credited = standings.credited_games(
            standings.Result(
                "w",
                "l",
                rubber.outcome or standings.PLAYED,
                tuple((a, b) if rubber_a_won else (b, a) for a, b in rubber.games),
                best_of=event.best_of,
            )
        )
        # `credited` is from the rubber's winner; `games` is kept from the tie winner's side.
        games += credited if mine else [(lost_by, won_by) for won_by, lost_by in credited]
    if match.outcome in (Match.Outcome.WALKOVER, Match.Outcome.RETIRED):
        # A tie that wasn't played, or wasn't finished, is completed in the winner's favour: the wins
        # still needed, each in straight games to nil.
        missing = max(event.tie_wins_needed - won, 0)
        won += missing
        games += [(standings.GAME_POINTS, 0)] * (missing * (event.best_of // 2 + 1))
    return standings.Result(
        str(match.winner_id),
        str(loser),
        match.outcome or standings.PLAYED,
        tuple(games),
        best_of=event.best_of,
        rubbers=(won, lost),
    )


def describe(match: Match, viewer, staff: bool) -> dict:
    """The tie as TieSerializer shows it to `viewer`. A lineup's picks are shown to the team itself and
    to staff until both are in; everybody else learns only that it has been handed in."""
    event = match.draw.event
    match = (
        Match.objects.select_related("draw__event__tournament")
        .prefetch_related("rubbers__players__user")
        .get(pk=match.pk)
    )
    rubbers = list(match.rubbers.all())
    begun = bool(rubbers)
    lineups = {lineup.entry_id: lineup for lineup in match.lineups.all()}
    open_now = not begun and _lineups_open(match)

    def side(entry_id) -> dict:
        entry = Entry.objects.filter(pk=entry_id).first() if entry_id else None
        captain = entry is not None and entry.captain_id == viewer.id
        on_team = entry is not None and entry.players.filter(user=viewer).exists()
        lineup = lineups.get(entry_id)
        return {
            "submitted": lineup is not None,
            "submitted_at": lineup.submitted_at if lineup else None,
            "can_submit": open_now and (staff or captain),
            "picks": lineup.picks if lineup and not begun and (staff or on_team) else None,
        }

    a, b = tie_score(match)
    return {
        "wins_needed": event.tie_wins_needed,
        "template": event.tie_rubbers,
        "begun": begun,
        "score": [a, b],
        "a": side(match.entry_a_id),
        "b": side(match.entry_b_id),
        "can_reset": staff
        and begun
        and match.status == Match.Status.SCHEDULED
        and all(rubber.status == R.SCHEDULED for rubber in rubbers),
        "rubbers": [
            {
                "id": rubber.id,
                "position": rubber.position,
                "kind": rubber.kind,
                "status": rubber.status,
                "a_players": [p.user for p in rubber.players.all() if p.side == RubberPlayer.Side.A],
                "b_players": [p.user for p in rubber.players.all() if p.side == RubberPlayer.Side.B],
                "winner_id": rubber.winner_id,
                "outcome": rubber.outcome,
                "games": rubber.games,
            }
            for rubber in rubbers
        ],
    }


def _lineups_open(match: Match) -> bool:
    try:
        ensure_lineups_open(match)
    except ApiException:
        return False
    return True
