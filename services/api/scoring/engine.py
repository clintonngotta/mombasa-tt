"""The scoring rules of table tennis, for validating score streams on the server (REQ-012).

This is written independently of the TypeScript reducer the scoring deck runs
(packages/scoring/src/index.ts). Both read the same fixtures (packages/scoring/fixtures) and must give
the same canonical state after every event, so a stream the deck accepted is accepted here and nowhere
else is a rule decided twice differently.

Rules: ITTF Laws of Table Tennis 2.11 (a game), 2.12 (a match), 2.13 (order of serving, receiving and
ends) and Regulations 3.4.4.2 (time-out), as transcribed in spec.md.

A state is a plain dict with the keys of `initial_state()`; an event is a dict with a `type`.
"""

from copy import deepcopy

GAME_POINTS = 11
PLAYERS = ("a1", "a2", "b1", "b2")
SIDES = ("a", "b")
ENDS = ("left", "right")


class ScoringError(Exception):
    """An event that the rules don't allow where it stands. `code` matches the TypeScript ErrorCode."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def partner_of(player: str) -> str:
    return player[0] + ("2" if player[1] == "1" else "1")


def games_needed(best_of: int) -> int:
    return best_of // 2 + 1


def initial_state() -> dict:
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

    # 2.13.3: service changes after every 2 points, and after every point once both have 10.
    if (a >= 10 and b >= 10) or (a + b) % 2 == 0:
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
    if player != state["server"]:
        # 2.13.4: the receiver is whoever served to the chosen server in the game before: the partner
        # of the player who would otherwise have received.
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
    state["timeouts"][SIDES.index(side)] = True
    return state


_HANDLERS = {"start": _start, "point": _point, "choose_server": _choose_server, "timeout": _timeout}


def apply(config: dict, state: dict, event: dict) -> dict:
    """The state after one event that isn't an undo; `state` itself is left as it was."""
    handler = _HANDLERS.get(event.get("type"))
    if handler is None:
        raise ScoringError("unknown_event")
    return handler(config, deepcopy(state), event)


class Scoring:
    """A match being scored: the state now and the states an undo goes back to. A refused event
    raises and changes nothing."""

    def __init__(self, config: dict):
        self.config = config
        self.state = initial_state()
        self._earlier: list[dict] = []

    def push(self, event: dict) -> dict:
        if event.get("type") == "undo":
            if not self._earlier:
                raise ScoringError("nothing_to_undo")
            self.state = self._earlier.pop()
        else:
            after = apply(self.config, self.state, event)
            self._earlier.append(self.state)
            self.state = after
        return self.state


def replay(config: dict, events: list[dict]) -> list[dict]:
    """The state after every event of a stream. Raises ScoringError on the first one not allowed."""
    scoring = Scoring(config)
    return [deepcopy(scoring.push(event)) for event in events]
