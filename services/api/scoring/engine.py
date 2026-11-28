"""The scoring rules of table tennis, for validating score streams on the server (REQ-012).

This is written independently of the TypeScript reducer the scoring deck runs
(packages/scoring/src/index.ts). Both read the same fixtures (packages/scoring/fixtures) and must give
the same canonical state after every event, so a stream the deck accepted is accepted here and nowhere
else is a rule decided twice differently.

Rules: ITTF Laws of Table Tennis 2.11 (a game), 2.12 (a match), 2.13 (order of serving, receiving and
ends), 2.15 (the expedite system) and Regulations 3.4.4.2 (time-out), 3.5.2 (cards and penalty points)
and 3.4.2.3 (suspension for incapacity), as transcribed in spec.md.

A state is a plain dict with the keys of `initial_state()`; an event is a dict with a `type`.
"""

from copy import deepcopy

GAME_POINTS = 11
PLAYERS = ("a1", "a2", "b1", "b2")
SIDES = ("a", "b")
ENDS = ("left", "right")
CARD_REASONS = ("bad_behaviour", "racket_abuse", "illegal_advice", "delay", "other")
WALKOVER_REASONS = ("no_show", "withdrawal", "injury")
LADDER_MAX = 3  # a fourth offence is the referee's to decide (3.5.2.4)


class ScoringError(Exception):
    """An event that the rules don't allow where it stands. `code` matches the TypeScript ErrorCode."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def partner_of(player: str) -> str:
    return player[0] + ("2" if player[1] == "1" else "1")


def games_needed(best_of: int) -> int:
    return best_of // 2 + 1


def check_config(config) -> None:
    """Refuse a configuration the rules don't know: best of 3, 5 or 7, singles or doubles."""
    known = (
        isinstance(config, dict)
        and type(config.get("best_of")) is int
        and config["best_of"] in (3, 5, 7)
        and isinstance(config.get("doubles"), bool)
    )
    if not known:
        raise ScoringError("invalid_config")
    if "carry" in config:
        carry = config["carry"]

        def count(n, most):
            return type(n) is int and 0 <= n <= most

        offences = carry.get("offences") if isinstance(carry, dict) else None
        advisers = carry.get("advisers") if isinstance(carry, dict) else None
        fine = (
            isinstance(offences, dict)
            and all(count(offences.get(player), LADDER_MAX) for player in PLAYERS)
            and isinstance(advisers, list)
            and len(advisers) == 2
            and all(count(n, 2) for n in advisers)
        )
        if not fine:
            raise ScoringError("invalid_config")


def initial_state(config: dict | None = None) -> dict:
    """The state before the first event; a tie's rubber starts with what the tie carries (3.5.2.7)."""
    carry = (config or {}).get("carry")
    return {
        "status": "not_started",
        "game_number": 1,
        "games": [],
        "games_won": [0, 0],
        "points": [0, 0],
        "server": None,
        "receiver": None,
        "first_server": None,
        "first_receiver": None,
        "a_end": None,
        "decider_changed": False,
        "timeouts": [False, False],
        "winner": None,
        "outcome": None,
        "timeout_running": [False, False],
        "offences": {player: carry["offences"][player] for player in PLAYERS}
        if carry
        else dict.fromkeys(PLAYERS, 0),
        "advisers": list(carry["advisers"]) if carry else [0, 0],
        "suspended": None,
        "expedite": False,
    }


def _other_end(end: str) -> str:
    return "right" if end == "left" else "left"


def _start(config: dict, state: dict, event: dict) -> dict:
    if state["status"] != "not_started":
        raise ScoringError("already_started")
    server, receiver, a_end = event.get("server"), event.get("receiver"), event.get("a_end")
    if server not in PLAYERS or a_end not in ENDS:
        raise ScoringError("invalid_start")
    if config["doubles"]:
        # 2.13.4: in the first game the receiving pair decides which of them receives first.
        if receiver not in PLAYERS or receiver[0] == server[0]:
            raise ScoringError("invalid_start")
    else:
        if server[1] != "1":
            raise ScoringError("invalid_start")
        opponent = "b1" if server[0] == "a" else "a1"
        if receiver not in (None, opponent):
            raise ScoringError("invalid_start")
        receiver = opponent
    state.update(
        status="in_progress",
        server=server,
        receiver=receiver,
        first_server=server,
        first_receiver=receiver,
        a_end=a_end,
    )
    return state


def _point(config: dict, state: dict, event: dict) -> dict:
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    side = event.get("side")
    if side not in SIDES:
        raise ScoringError("unknown_event")
    if state["suspended"] is not None:
        raise ScoringError("suspended")
    # Play resumed: a time-out still running is over (the side may resume early).
    state["timeout_running"] = [False, False]
    who = SIDES.index(side)
    state["points"][who] += 1
    a, b = state["points"]
    most = max(a, b)

    # 2.11.1: first to 11, unless both reach 10; then the first to lead by 2.
    if most >= GAME_POINTS and abs(a - b) >= 2:
        state["games"].append([a, b])
        state["games_won"][who] += 1
        state["points"] = [0, 0]
        if state["games_won"][who] == games_needed(config["best_of"]):
            # 2.12.1: the match is the best of an odd number of games.
            state.update(
                status="completed",
                winner=side,
                outcome="played",
                server=None,
                receiver=None,
                first_server=None,
                first_receiver=None,
            )
            return state
        # 2.13.7: the next game starts at the other end. 2.13.6 and 2.13.4: the side that served first
        # receives first, and the first receiver is the player who served to the new server before.
        first_server, first_receiver = state["first_server"], state["first_receiver"]
        state.update(
            game_number=state["game_number"] + 1,
            decider_changed=False,
            a_end=_other_end(state["a_end"]),
            server=first_receiver,
            receiver=first_server,
            first_server=first_receiver,
            first_receiver=first_server,
        )
        return state

    # 2.13.3: service changes after every 2 points, and after every point once both have 10. 2.15.3:
    # under the expedite system, after every point.
    if state["expedite"] or (a >= 10 and b >= 10) or (a + b) % 2 == 0:
        server, receiver = state["server"], state["receiver"]
        # 2.13.5: in doubles the previous receiver serves and the previous server's partner receives.
        state["server"] = receiver
        state["receiver"] = partner_of(server) if config["doubles"] else server
    # 2.13.6-2.13.7: in the last possible game, when a side first reaches 5 the players change ends and,
    # in doubles, the pair due to receive next changes its order of receiving.
    if state["game_number"] == config["best_of"] and not state["decider_changed"] and most == 5:
        state["decider_changed"] = True
        state["a_end"] = _other_end(state["a_end"])
        if config["doubles"]:
            state["receiver"] = partner_of(state["receiver"])
    return state


def _choose_server(config: dict, state: dict, event: dict) -> dict:
    if not config["doubles"]:
        raise ScoringError("not_doubles")
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    # The first game's server is set at the start; later the choice is made before the first point.
    if state["game_number"] == 1 or sum(state["points"]) != 0:
        raise ScoringError("game_under_way")
    player = event.get("player")
    if player not in PLAYERS or player[0] != state["server"][0]:
        raise ScoringError("not_serving_pair")
    if player == state["server"]:
        return state  # already the server: nothing changes
    # 2.13.4: the receiver is whoever served to the chosen server in the game before: the partner of
    # the player who would otherwise have received.
    receiver = partner_of(state["receiver"])
    state.update(server=player, first_server=player, receiver=receiver, first_receiver=receiver)
    return state


def _timeout(config: dict, state: dict, event: dict) -> dict:
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    side = event.get("side")
    if side not in SIDES:
        raise ScoringError("unknown_event")
    # 3.4.4.2: one time-out for each player or pair in an individual match.
    if state["timeouts"][SIDES.index(side)]:
        raise ScoringError("timeout_used")
    # 3.4.4.2.3: both sides may claim one at the same time; play resumes when both are ready.
    state["timeouts"][SIDES.index(side)] = True
    state["timeout_running"][SIDES.index(side)] = True
    return state


def _timeout_end(config: dict, state: dict, event: dict) -> dict:
    if not any(state["timeout_running"]):
        raise ScoringError("no_timeout")
    state["timeout_running"] = [False, False]
    return state


def _other(side: str) -> str:
    return "b" if side == "a" else "a"


def offences_of(config: dict, state: dict, player: str) -> int:
    """How far up the card ladder a player's next offence starts (3.5.2.6): their own count, or in
    doubles the pair's, the higher of its two players' counts."""
    own = state["offences"][player]
    return max(own, state["offences"][partner_of(player)]) if config["doubles"] else own


def _card(config: dict, state: dict, event: dict) -> dict:
    """3.5.2.2-3.5.2.4: a player's first offence is a yellow card; the second and third are yellow and
    red together, giving the opponent 1 and then 2 penalty points; a fourth is for the referee."""
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    player = event.get("player")
    if player not in PLAYERS or (not config["doubles"] and player[1] != "1"):
        raise ScoringError("unknown_event")
    if event.get("reason") not in CARD_REASONS:
        raise ScoringError("invalid_card")
    # 3.5.2.6: in doubles a card for either player counts against the pair, so the pair stands at the
    # higher of its players' counts (carried in from earlier rubbers too); the offender takes the new step.
    reached = offences_of(config, state, player)
    if reached >= LADDER_MAX:
        raise ScoringError("refer_to_referee")
    state["offences"][player] = reached + 1
    owed = reached
    if owed == 0:
        return state
    # 3.5.2.3: penalty points are points to the opponent, which can end a game or the match. They are
    # played even if a suspension is running; it stands afterwards if the match goes on.
    suspended = state["suspended"]
    state["suspended"] = None
    for _ in range(owed):
        if state["status"] != "in_progress":
            break
        state = _point(config, state, {"side": _other(player[0])})
    state["suspended"] = suspended if state["status"] == "in_progress" else None
    return state


def _adviser_card(config: dict, state: dict, event: dict) -> dict:
    """3.5.2.1-3.5.2.2: an adviser is warned with a yellow card, then sent away with a red one."""
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    side = event.get("side")
    if side not in SIDES:
        raise ScoringError("unknown_event")
    if event.get("reason") not in CARD_REASONS:
        raise ScoringError("invalid_card")
    if state["advisers"][SIDES.index(side)] >= 2:
        raise ScoringError("adviser_sent_off")
    state["advisers"][SIDES.index(side)] += 1
    return state


def _suspension(config: dict, state: dict, event: dict) -> dict:
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    side = event.get("side")
    if side not in SIDES:
        raise ScoringError("unknown_event")
    if state["suspended"] is not None:
        raise ScoringError("suspended")
    state["suspended"] = side
    return state


def _suspension_end(config: dict, state: dict, event: dict) -> dict:
    if state["suspended"] is None:
        raise ScoringError("not_suspended")
    state["suspended"] = None
    return state


def _expedite(config: dict, state: dict, event: dict) -> dict:
    if state["status"] != "in_progress":
        raise ScoringError("not_in_progress")
    if state["expedite"]:
        raise ScoringError("expedite_on")
    played = sum(state["points"])
    # 2.15.1: not introduced in a game once at least 18 points have been scored.
    if played >= 18:
        raise ScoringError("expedite_too_late")
    state["expedite"] = True
    # 2.15.3: introduced between rallies, the player who received in the rally before serves. After an
    # odd number of points the server of that rally is still due, so service moves on one step.
    if played % 2 == 1:
        server = state["server"]
        state["server"] = state["receiver"]
        state["receiver"] = partner_of(server) if config["doubles"] else server
    return state


def _end_early(outcome: str):
    """The side retires or is disqualified: the opponent wins with the points played, nothing more."""

    def handler(config: dict, state: dict, event: dict) -> dict:
        if state["status"] != "in_progress":
            raise ScoringError("not_in_progress")
        side = event.get("side")
        if side not in SIDES:
            raise ScoringError("unknown_event")
        state.update(
            status="completed",
            winner=_other(side),
            outcome=outcome,
            timeout_running=[False, False],
            suspended=None,
            server=None,
            receiver=None,
            first_server=None,
            first_receiver=None,
        )
        return state

    return handler


def _walkover(config: dict, state: dict, event: dict) -> dict:
    """The side doesn't play: before the start, the match goes to the opponent with no games (REQ-043)."""
    if state["status"] != "not_started":
        raise ScoringError("already_started")
    side = event.get("side")
    if side not in SIDES:
        raise ScoringError("unknown_event")
    if event.get("reason") not in WALKOVER_REASONS:
        raise ScoringError("invalid_walkover")
    state.update(status="completed", winner=_other(side), outcome="walkover")
    return state


_HANDLERS = {
    "start": _start,
    "point": _point,
    "choose_server": _choose_server,
    "timeout": _timeout,
    "timeout_end": _timeout_end,
    "card": _card,
    "adviser_card": _adviser_card,
    "suspension": _suspension,
    "suspension_end": _suspension_end,
    "expedite": _expedite,
    "retire": _end_early("retired"),
    "disqualify": _end_early("disqualified"),
    "walkover": _walkover,
}


def apply(config: dict, state: dict, event: dict) -> dict:
    """The state after one event that isn't an undo; `state` itself is left as it was, and is what
    comes back when the event changes nothing."""
    kind = event.get("type") if isinstance(event, dict) else None
    handler = _HANDLERS.get(kind) if isinstance(kind, str) else None
    if handler is None:
        raise ScoringError("unknown_event")
    after = handler(config, deepcopy(state), event)
    return state if after == state else after


class Scoring:
    """A match being scored: the state now and the states an undo goes back to. A refused event
    raises and changes nothing."""

    def __init__(self, config: dict):
        check_config(config)
        self.config = config
        self.state = initial_state(config)
        self._earlier: list[dict] = []

    def push(self, event: dict) -> dict:
        """Undo goes back one action at a time for as long as there are actions: through a game
        boundary, a time-out, the end of the match and the start itself. The state returned is the
        engine's own: read it, don't change it."""
        if isinstance(event, dict) and event.get("type") == "undo":
            if not self._earlier:
                raise ScoringError("nothing_to_undo")
            self.state = self._earlier.pop()
        else:
            after = apply(self.config, self.state, event)
            if after is not self.state:  # an event that changed nothing leaves nothing to undo
                self._earlier.append(self.state)
                self.state = after
        return self.state


def replay(config: dict, events: list[dict]) -> list[dict]:
    """The state after every event of a stream. Raises ScoringError on the first one not allowed."""
    scoring = Scoring(config)
    return [deepcopy(scoring.push(event)) for event in events]
