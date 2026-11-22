"""What viewers see of a match being scored (REQ-043, TASK-084).

The score here is the server's own replay of the umpire's accepted events, read from the sheet's saved
state: games, points, who serves, time-outs, the match's standing incidents. It never carries the
events themselves, the umpire's notes, the assignment or anything else the deck works with, so a live
view has nothing it could score with (REQ-010). Pages hear that a match changed over the tournament's
socket and fetch this again; it is never pushed with the message.
"""

from django.core.cache import cache
from django.db.models import Max, Prefetch, Q

from competitions import drawing, official
from competitions.models import DrawVersion, Match, Rubber, Tournament

from .models import MatchIncident, Scorecard

# A tournament has as many matches in play as it has tables; this is a ceiling, not a page size.
MAX_LIVE = 64
# Every viewer fetches the list again after each point; for a second they share one answer.
CACHE_SECONDS = 1


def score_of(scorecard: Scorecard | None, players: dict[str, list] | None = None) -> dict | None:
    """The live score of a sheet that has been started, None before its first event. `players` (the
    users of each side in slot order) names the server in doubles; without it only the side is given."""
    if scorecard is None or not scorecard.revision:
        return None
    state = scorecard.state or {}
    server = state.get("server")
    server_name = ""
    if server and players:
        people = players.get(server[0], [])
        position = int(server[1]) - 1
        server_name = people[position].display_name if position < len(people) else ""
    return {
        "status": state.get("status", "not_started"),
        "outcome": state.get("outcome"),
        "winner": state.get("winner"),
        "game_number": state.get("game_number", 1),
        "games": state.get("games", []),
        "games_won": state.get("games_won", [0, 0]),
        "points": state.get("points", [0, 0]),
        "server": server[0] if server else None,
        "server_name": server_name,
        "timeouts": state.get("timeouts", [False, False]),
        "timeout_running": state.get("timeout_running", [False, False]),
        "suspended": state.get("suspended"),
        "expedite": state.get("expedite", False),
        "revision": scorecard.revision,
    }


def _players(scorecard: Scorecard) -> dict[str, list]:
    """The sheet's players by side from what live_matches prefetched (no query of its own)."""
    if scorecard.rubber_id:
        placed = list(scorecard.rubber.players.all())
        return {side: [p.user for p in placed if p.side == side] for side in ("a", "b")}
    match = scorecard.match
    return {
        "a": [place.user for place in match.entry_a.players.all()] if match.entry_a else [],
        "b": [place.user for place in match.entry_b.players.all()] if match.entry_b else [],
    }


def _cards(incidents) -> list[dict]:
    """The cards shown so far, as everybody may see them: no notes."""
    return [
        {
            "side": incident.side,
            "player_name": incident.player.display_name if incident.player else "",
            "card": incident.card,
            "penalty_points": incident.penalty_points,
            "adviser": incident.kind == MatchIncident.Kind.ADVISER_CARD,
            "reason": incident.reason,
            "game_number": incident.game_number,
        }
        for incident in incidents
        if incident.kind in (MatchIncident.Kind.CARD, MatchIncident.Kind.ADVISER_CARD)
    ]


def live_matches(tournament: Tournament) -> list[dict]:
    """The tournament's matches being scored now, from published draws: started sheets not yet
    confirmed. Loaded in a fixed number of queries whatever the number of matches."""
    published = DrawVersion.Status.PUBLISHED
    sheets = list(
        Scorecard.objects.filter(revision__gt=0, confirmed_at__isnull=True)
        .filter(
            # Decided matches and rubbers are left out before the cap, so a sheet nobody confirmed never
            # takes the place of a match being played.
            Q(
                match__draw__event__tournament=tournament,
                match__draw__status=published,
                match__status=Match.Status.SCHEDULED,
            )
            | Q(
                rubber__match__draw__event__tournament=tournament,
                rubber__match__draw__status=published,
                rubber__match__status=Match.Status.SCHEDULED,
                rubber__status=Rubber.Status.SCHEDULED,
            )
        )
        .select_related(
            "match__draw__event",
            "match__table",
            "match__entry_a",
            "match__entry_b",
            "rubber__match__draw__event",
            "rubber__match__table",
            "rubber__match__entry_a",
            "rubber__match__entry_b",
        )
        .prefetch_related(
            Prefetch("match__entry_a__players", queryset=_entry_places()),
            Prefetch("match__entry_b__players", queryset=_entry_places()),
            Prefetch("rubber__match__entry_a__players", queryset=_entry_places()),
            Prefetch("rubber__match__entry_b__players", queryset=_entry_places()),
            Prefetch("rubber__players", queryset=_rubber_places()),
            Prefetch(
                "incidents", queryset=MatchIncident.objects.select_related("player").order_by("sequence")
            ),
        )
        .order_by("assigned_at", "id")[:MAX_LIVE]
    )
    matches = [sheet.tie_or_match for sheet in sheets]
    rounds = _rounds([match.draw_id for match in matches])
    ties = _rubbers_won([match.id for match in matches if match.draw.event.is_team])
    shown = []
    for sheet, match in zip(sheets, matches, strict=True):
        shown.append(
            {
                "match_id": match.id,
                "event_id": match.draw.event_id,
                "event_name": match.draw.event.name,
                "round": _round_label(match, rounds),
                "table": match.table.label if match.table else "",
                "a": official.title(match.entry_a),
                "b": official.title(match.entry_b),
                "rubber": sheet.rubber.position if sheet.rubber_id else None,
                "rubbers_won": ties.get(match.id),
                "score": score_of(sheet, _players(sheet)),
                "cards": _cards(sheet.incidents.all()),
            }
        )
    return shown


def _entry_places():
    from competitions.models import EntryPlayer

    # The model's own order, the one service.players_of reads slots in.
    return EntryPlayer.objects.select_related("user")


def _rubber_places():
    from competitions.models import RubberPlayer

    return RubberPlayer.objects.select_related("user")


def _rounds(draw_ids: list) -> dict:
    """The number of knockout rounds of each draw, to name a round "Semi-final" and so on."""
    found = (
        Match.objects.filter(draw_id__in=set(draw_ids), stage=Match.Stage.KNOCKOUT)
        .values("draw_id")
        .annotate(rounds=Max("round"))
    )
    return {row["draw_id"]: row["rounds"] for row in found}


def _round_label(match: Match, rounds: dict) -> str:
    if match.stage == Match.Stage.GROUP:
        return (
            f"{drawing.group_name(match.group)} · Round {match.round}"
            if match.group
            else f"Round {match.round}"
        )
    total = rounds.get(match.draw_id)
    return drawing.round_name(match.round, total) if total else f"Round {match.round}"


def _rubbers_won(tie_ids: list) -> dict:
    """[rubbers won by side a, by side b] for each tie under way."""
    won: dict = {tie_id: [0, 0] for tie_id in tie_ids}
    decided = Rubber.objects.filter(match_id__in=tie_ids, status=Rubber.Status.COMPLETED).select_related(
        "match"
    )
    for rubber in decided:
        if rubber.winner_id is None:
            continue
        side = 0 if rubber.winner_id == rubber.match.entry_a_id else 1
        won[rubber.match_id][side] += 1
    return won


def cache_key(tournament_id) -> str:
    return f"live:{tournament_id}"


def shown_live(tournament: Tournament) -> list[dict]:
    """live_matches, shared by every viewer for a second. The list is the same for everybody who may see
    the tournament (the caller checks that first), so sharing it shows nobody anything new."""
    key = cache_key(tournament.id)
    found = cache.get(key)
    if found is None:
        found = live_matches(tournament)
        cache.set(key, found, CACHE_SECONDS)
    return found


def forget(tournament_id) -> None:
    """A score changed: the next viewer gets it fresh, not the second-old list."""
    cache.delete(cache_key(tournament_id))
