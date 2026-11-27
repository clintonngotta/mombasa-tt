"""Match recaps and result cards (REQ-018, TASK-032).

A recap is the official result and nothing else: who played, the games, who won, and each player's
rating change once the ledger has it. While the result waits for the rating worker it says "processing"
rather than inventing a number. Nothing is inferred from score presses (no aces, rallies or shots).
The card is a PNG with the same public facts, for sharing.
"""

from core import brand
from ratings.models import RatingEvent

from .models import Match, OfficialResult
from .official import title


def _sides(match: Match):
    return {"a": match.entry_a, "b": match.entry_b}


def recap(match: Match) -> dict:
    result = (
        OfficialResult.objects.filter(match=match, rubber__isnull=True, current=True)
        .select_related("winner")
        .first()
    )
    sides = _sides(match)
    players = []
    for side, entry in sides.items():
        for place in entry.players.all() if entry else []:
            players.append({"side": side, "user_id": place.user_id, "display_name": place.user.display_name})
    rating = "none"
    changes = []
    if result is not None:
        events = {e.user_id: e for e in RatingEvent.objects.filter(match=match, rubber__isnull=True)}
        if events:
            rating = "done"
            for player in players:
                event = events.get(player["user_id"])
                if event:
                    changes.append(
                        {
                            "user_id": player["user_id"],
                            "display_name": player["display_name"],
                            "before": round(event.before),
                            "after": round(event.after),
                            "delta": round(event.delta),
                        }
                    )
        elif result.projected_at is None:
            rating = "processing"
        else:
            rating = (
                "unrated"  # walkover, retirement, disqualification, a tie as a whole, a club's local Jumbles
            )
    event = match.draw.event
    tournament = event.tournament
    winner_side = None
    if result is not None:
        winner_side = "a" if result.winner_id == match.entry_a_id else "b"
    return {
        "match_id": match.id,
        "tournament_id": tournament.id,
        "tournament_name": tournament.name,
        "event_id": event.id,
        "event_name": event.name,
        "side_a": title(sides["a"]),
        "side_b": title(sides["b"]),
        "official": result is not None,
        "outcome": result.outcome if result else "",
        "winner_side": winner_side,
        "games": [list(g) for g in (result.games if result else [])],
        "players": players,
        "rating": rating,
        "rating_changes": changes,
    }


# How the card marks a match that wasn't played to a finish.
CARD_OUTCOME = {"walkover": " (W/O)", "retired": " (ret.)", "disqualified": " (DQ)"}


def card_png(shown: dict) -> bytes:
    """The result as a share image."""
    return brand.share_image(
        shown["tournament_name"],
        shown["event_name"],
        [brand.Card("Result", card_rows(shown), big=True)],
    )


def card_rows(shown: dict) -> list[brand.Row]:
    """Each side with the games it won, the scores and the winner. Public facts only. A game left
    unfinished by a retirement or a disqualification is shown but not counted as won (REQ-043)."""
    finished = [(a, b) for a, b in shown["games"] if max(a, b) >= 11 and abs(a - b) >= 2]
    won_a = sum(1 for a, b in finished if a > b)
    sides = [
        (shown["side_a"], won_a, shown["winner_side"] == "a"),
        (shown["side_b"], len(finished) - won_a, shown["winner_side"] == "b"),
    ]
    rows = [
        brand.Row(name or "To be decided", str(games) if shown["official"] else "", strong=won)
        for name, games, won in sides
    ]
    if shown["games"]:
        rows.append(brand.Row("Games  " + "   ".join(f"{a}-{b}" for a, b in shown["games"]), note=True))
    winner = next((name for name, _, won in sides if won), "")
    if winner:
        rows.append(brand.Row(f"{winner} wins{CARD_OUTCOME.get(shown['outcome'], '')}", note=True))
    elif not shown["official"]:
        rows.append(brand.Row("Not played yet", note=True))
    return rows


def published_match(tournament_pk, event_pk, pk) -> Match | None:
    """A match of an event's published draw in a tournament that isn't a draft: what anyone, signed in
    or not, may see the result of."""
    from .models import DrawVersion, Tournament

    return (
        Match.objects.select_related("draw__event__tournament", "entry_a", "entry_b")
        .prefetch_related("entry_a__players__user", "entry_b__players__user")
        .filter(
            pk=pk,
            draw__event_id=event_pk,
            draw__event__tournament_id=tournament_pk,
            draw__status=DrawVersion.Status.PUBLISHED,
        )
        .exclude(draw__event__tournament__status=Tournament.Status.DRAFT)
        .first()
    )
