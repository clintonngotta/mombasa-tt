"""Match recaps and result cards (REQ-018, TASK-032).

A recap is the official result and nothing else: who played, the games, who won, and each player's
rating change once the ledger has it. While the result waits for the rating worker it says "processing"
rather than inventing a number. Nothing is inferred from score presses (no aces, rallies or shots).
The card is an SVG with the same public facts, for sharing.
"""

from html import escape

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
            rating = "unrated"  # walkover, retirement, a tie as a whole, a club's local Jumbles
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


NAVY, GOLD, WHITE, MUTED = "#0b1f3a", "#f2b705", "#ffffff", "#9fb3c8"


def _text(x, y, fill, size, content, *, bold=False, end=False) -> str:
    weight = ' font-weight="700"' if bold else ""
    anchor = ' text-anchor="end"' if end else ""
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="sans-serif" font-size="{size}"{weight}{anchor}>'
        f"{escape(str(content))}</text>"
    )


def card_svg(shown: dict) -> str:
    """A 1080x1080 result card: tournament, event, sides, games and the winner. Public facts only."""
    won_a = sum(1 for a, b in shown["games"] if a > b)
    sides = [
        (shown["side_a"], won_a, shown["winner_side"] == "a"),
        (shown["side_b"], len(shown["games"]) - won_a, shown["winner_side"] == "b"),
    ]
    winner = next((name for name, _, won in sides if won), "")
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080">',
        f'<rect width="1080" height="1080" fill="{NAVY}"/>',
        f'<rect x="0" y="0" width="1080" height="16" fill="{GOLD}"/>',
        _text(80, 140, GOLD, 40, "COAST TT", bold=True),
        _text(80, 220, WHITE, 52, shown["tournament_name"][:40], bold=True),
        _text(80, 280, MUTED, 36, shown["event_name"][:50]),
    ]
    for i, (name, games, won) in enumerate(sides):
        y = 460 + i * 170
        colour = GOLD if won else WHITE
        lines.append(_text(80, y, colour, 54, (name or "To be decided")[:30], bold=True))
        lines.append(_text(1000, y, colour, 96, games, bold=True, end=True))
    lines.append(_text(80, 830, MUTED, 40, "  ".join(f"{a}-{b}" for a, b in shown["games"])))
    if winner:
        lines.append(_text(80, 960, GOLD, 44, f"{winner[:36]} wins", bold=True))
    elif not shown["official"]:
        lines.append(_text(80, 960, MUTED, 44, "Not played yet"))
    lines.append("</svg>")
    return "\n".join(lines)


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
