"""Results entered or corrected by the organizers (REQ-015).

A correction writes a new version of the official result and keeps the one it replaces, with who
made it and why. If it changes who goes on, the place in the later match is put right at once when
nothing has happened there yet. When that match has already started (it is on a table, being scored
or decided), nobody is replaced silently: the event is paused and a `Resolution` waits for the
organizers to choose between keeping the later match as played and putting the right entry in.
"""

from django.db.models import Q
from django.utils import timezone

from core.exceptions import ApiException

from . import drawing, official, signals
from .models import DrawVersion, Entry, Event, Match, Resolution, Rubber, Tournament

Source = official.Source


def _conflict(code: str, message: str) -> ApiException:
    return ApiException(code, message, 409)


def _ensure_open(match: Match) -> None:
    event = match.draw.event
    if match.draw.status != DrawVersion.Status.PUBLISHED:
        raise _conflict("draw_not_published", "Only matches of the published draw have results.")
    if event.is_closed or event.tournament.is_closed:
        raise _conflict("event_closed", "This event is over, so its results can't change here.")


def enter(match: Match, rubber: Rubber | None, winner: Entry, outcome: str, games, actor) -> None:
    """The organizers record a result themselves: a walkover, a retirement or a paper score sheet. It
    is official at once, like a result confirmed on the scoring deck."""
    _ensure_open(match)
    event = match.draw.event
    if event.tournament.status != Tournament.Status.IN_PROGRESS or event.status != Event.Status.IN_PROGRESS:
        raise _conflict("not_in_play", "Start the tournament and the event before recording results.")
    from . import ties  # ties builds on drawing, as this does

    if rubber is not None:
        ties.record_rubber(rubber, winner, outcome=outcome, games=games, actor=actor, source=Source.STAFF)
    else:
        drawing.record_result(match, winner, outcome=outcome, games=games, actor=actor, source=Source.STAFF)


def started(match: Match) -> bool:
    """Something has happened in the match that replacing an opponent would undo."""
    from scoring.models import Scorecard  # scoring builds on competitions

    if match.status == Match.Status.COMPLETED or match.dispatched_at is not None:
        return True
    if match.rubbers.exclude(status=Rubber.Status.SCHEDULED).exists():
        return True
    return Scorecard.objects.filter(Q(match=match) | Q(rubber__match=match), revision__gt=0).exists()


def correct(
    match: Match, rubber: Rubber | None, winner: Entry, outcome: str, games, actor, reason: str
) -> list[Resolution]:
    """Replace the official result of a decided match or rubber. Returns the resolutions it opened:
    later matches that had started with an entry the correction says should not be there."""
    _ensure_open(match)
    official.ensure_not_held(match)
    standing = official.current(match, rubber)
    if standing is None:
        raise _conflict("no_result", "There is no official result to correct yet.")
    if winner.id not in (match.entry_a_id, match.entry_b_id):
        raise _conflict("not_in_match", "The winner is one of the two sides of the match.")
    games = [list(game) for game in games]
    if (standing.winner_id, standing.outcome, standing.games) == (winner.id, outcome, games):
        raise _conflict("nothing_to_correct", "That is the result as it already stands.")
    event = match.draw.event
    a_won = winner.id == match.entry_a_id
    if rubber is not None:
        _ensure_tie_ends_the_same(match, rubber, winner)
        drawing.check_games(event.best_of, games, outcome, a_won=a_won)
        target = rubber
    elif event.is_team:
        raise _conflict("correct_the_rubbers", "A tie is corrected through its rubbers.")
    else:
        drawing.check_games(event.best_of, games, outcome, a_won=a_won)
        target = match
    winner_changed = target.winner_id != winner.id
    target.winner, target.outcome, target.games = winner, outcome, games
    target.save(update_fields=["winner", "outcome", "games"])
    result = official.accept(
        match, rubber, winner, outcome, games, actor=actor, source=Source.CORRECTION, reason=reason
    )
    opened: list[Resolution] = []
    if match.stage == Match.Stage.GROUP:
        # Any change in a group can change its order, and so who qualifies from which place.
        if match.status == Match.Status.COMPLETED:
            opened += _requalify(match.draw, match.group, result)
    elif winner_changed and rubber is None:
        opened += _move_on(match, winner, result)
    drawing.mark_ready(match.draw)
    signals.result_corrected.send(sender=Match, match=match, result=result)
    return opened


def _ensure_tie_ends_the_same(match: Match, rubber: Rubber, winner: Entry) -> None:
    """A rubber can be corrected as long as the tie still ends where and how it did. One that would
    change the tie's winner, or which rubbers had to be played, is refused."""
    if rubber.status != Rubber.Status.COMPLETED:
        raise _conflict("no_result", "There is no official result to correct yet.")
    needed = match.draw.event.tie_wins_needed or 0
    played = list(match.rubbers.filter(status=Rubber.Status.COMPLETED).order_by("position"))
    wins = {match.entry_a_id: 0, match.entry_b_id: 0}
    reached = None  # (position, entry id) where a team first has the wins it needs
    for one in played:
        taker = winner.id if one.id == rubber.id else one.winner_id
        wins[taker] += 1
        if reached is None and wins[taker] >= needed:
            reached = (one.position, taker)
    by_rubbers = match.status == Match.Status.COMPLETED and match.outcome == Match.Outcome.PLAYED
    expected = (played[-1].position, match.winner_id) if by_rubbers else None
    if reached != expected:
        raise _conflict(
            "tie_would_change",
            "This correction would change how the tie ended. Ties whose outcome changes can't be corrected "
            "here yet.",
        )


def _set_sides(match: Match, changes: dict[str, Entry | None], cause) -> list[Resolution]:
    """Put the right entries into `match` ({"a": entry, "b": entry}), or ask when it has started."""
    changes = {
        side: entry
        for side, entry in changes.items()
        if getattr(match, f"entry_{side}_id") != (entry.id if entry else None)
    }
    if not changes:
        return []
    if match.status == Match.Status.BYE:
        # Nothing is played in a bye: whoever stands there is through, and so moves on in turn.
        match.entry_a = match.winner = changes["a"]
        match.save(update_fields=["entry_a", "winner"])
        return _move_on(match, changes["a"], cause)
    if started(match):
        event = match.draw.event
        if event.paused_at is None:
            event.paused_at = timezone.now()
            event.save(update_fields=["paused_at"])
        return [
            Resolution.objects.create(
                event=event,
                match=match,
                side=side,
                old_entry=getattr(match, f"entry_{side}"),
                new_entry=entry,
                cause=cause,
            )
            for side, entry in changes.items()
        ]
    for side, entry in changes.items():
        setattr(match, f"entry_{side}", entry)
    match.ready_since = None  # its waiting starts again when both sides are known (mark_ready)
    match.save(update_fields=["entry_a", "entry_b", "ready_since"])
    # Lineups handed in for a tie against the other team no longer mean anything.
    match.rubbers.all().delete()
    match.lineups.all().delete()
    return []


def _move_on(match: Match, winner: Entry | None, cause) -> list[Resolution]:
    """The winner of `match` is now `winner` (nobody, if it is to be played again): put that right in
    the match it feeds."""
    opened = []
    for side in ("a", "b"):
        for later in Match.objects.filter(**{f"feeder_{side}": match}).select_related("draw__event"):
            opened += _set_sides(later, {side: winner}, cause)
    return opened


def _requalify(draw: DrawVersion, group: int, cause) -> list[Resolution]:
    """The group's order after a correction: put its qualifiers where they now belong."""
    rows, complete = drawing.group_table(draw, group)
    if not complete:
        return []
    entries = Entry.objects.in_bulk([row.member for row in rows])
    wanted: dict = {}  # match id -> {side: entry}
    knockout = {match.id: match for match in draw.matches.filter(stage=Match.Stage.KNOCKOUT)}
    for row in rows:
        for match in knockout.values():
            for side in ("a", "b"):
                from_here = getattr(match, f"{side}_from_group") == group
                if from_here and getattr(match, f"{side}_from_rank") == row.rank:
                    wanted.setdefault(match.id, {})[side] = entries[_as_key(row.member, entries)]
    opened = []
    for match_id, changes in wanted.items():
        opened += _set_sides(knockout[match_id], changes, cause)
    return opened


def _as_key(member, entries: dict):
    """Standings carry entry ids as text; `in_bulk` keys them as UUIDs."""
    return next(key for key in entries if str(key) == str(member))


def resolve(resolution: Resolution, choice: str, note: str, actor) -> list[Resolution]:
    """The organizers decide about a later match that had started. `keep`: it stands as played, with
    the entry that was there. `replace`: the right entry goes in and what was played there is struck
    out (kept on the resolution for the record). Returns resolutions that striking it out opened in
    turn, when the match after it had started as well."""
    if resolution.resolved_at is not None:
        raise _conflict("already_resolved", "This has already been decided.")
    match = resolution.match
    opened: list[Resolution] = []
    if choice == Resolution.Choice.REPLACE:
        opened = _replace(resolution, match, actor)
    resolution.choice = choice
    resolution.note = note
    resolution.resolved_by = actor
    resolution.resolved_at = timezone.now()
    resolution.save(update_fields=["choice", "note", "resolved_by", "resolved_at", "struck_out"])
    event = resolution.event
    if not event.resolutions.filter(resolved_at__isnull=True).exists():
        event.paused_at = None
        event.save(update_fields=["paused_at"])
    drawing.mark_ready(match.draw)
    return opened


def _replace(resolution: Resolution, match: Match, actor) -> list[Resolution]:
    from reservations import service as reservations  # both build on competitions
    from scoring import service as scoring
    from scoring.models import Scorecard

    scored = Scorecard.objects.filter(rubber__match=match, revision__gt=0).exists()
    if scored or match.rubbers.exclude(status=Rubber.Status.SCHEDULED).exists():
        raise _conflict(
            "tie_started",
            "Rubbers of this tie have been played or scored. It can only be kept as played here.",
        )
    if match.dispatched_at is not None and match.status == Match.Status.SCHEDULED:
        reservations.recall(match, actor, "A corrected result changed who plays this match.")
        match.refresh_from_db()
    struck = {"sheets": scoring.strike_out(match)}
    opened: list[Resolution] = []
    if match.status == Match.Status.COMPLETED:
        standing = official.current(match)
        struck["result"] = {
            "winner_id": str(match.winner_id),
            "outcome": match.outcome,
            "games": match.games,
            "version": standing.version if standing else None,
        }
        if standing:
            official.strike_out(standing)
        match.status = Match.Status.SCHEDULED
        match.winner, match.outcome, match.games = None, "", []
        match.save(update_fields=["status", "winner", "outcome", "games"])
        # Whoever went on from here no longer has: the match after it waits for this one again.
        opened = _move_on(match, None, resolution.cause)
    setattr(match, f"entry_{resolution.side}", resolution.new_entry)
    match.ready_since = None
    match.dispatched_at = None
    match.save(update_fields=["entry_a", "entry_b", "ready_since", "dispatched_at"])
    match.rubbers.all().delete()
    match.lineups.all().delete()
    resolution.struck_out = struck
    return opened
