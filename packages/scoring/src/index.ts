// The scoring rules of table tennis as a pure reducer (REQ-012): a stream of score events in, one
// canonical match state out. No clock, no storage, no network, so the same code runs in the PWA's
// scoring deck, offline, and in a future native client. The API validates accepted streams with an
// independent Python implementation (services/api/scoring/engine.py); both must give the states in
// ../fixtures after every event.
//
// Rules: ITTF Laws of Table Tennis 2.11 (a game), 2.12 (a match), 2.13 (order of serving, receiving
// and ends) and Regulations 3.4.4.2 (time-out), as transcribed in spec.md.

export type Side = "a" | "b"
export type Player = "a1" | "a2" | "b1" | "b2"
export type End = "left" | "right"

export interface Config {
  best_of: 3 | 5 | 7
  doubles: boolean
}

export type ScoreEvent =
  /** The umpire's set-up: who serves and receives first, and the end side a starts at. */
  | { type: "start"; server: Player; receiver?: Player; a_end: End }
  | { type: "point"; side: Side }
  /** Doubles, before the first point of a later game: which of the serving pair serves first. */
  | { type: "choose_server"; player: Player }
  | { type: "timeout"; side: Side }
  /** Takes back the last action that still stands. The undo itself stays in the stream. */
  | { type: "undo" }

export interface State {
  status: "not_started" | "in_progress" | "completed"
  /** 1-based number of the game being played; the last game once the match is over. */
  game_number: number
  /** Points of each finished game as [a, b], in playing order. */
  games: [number, number][]
  games_won: [number, number]
  /** Points in the game being played as [a, b]. */
  points: [number, number]
  server: Player | null
  receiver: Player | null
  /** Who served and received the first point of the game being played. */
  first_server: Player | null
  first_receiver: Player | null
  a_end: End | null
  /** The deciding game's change of ends (and of receiving order in doubles) has happened. */
  decider_changed: boolean
  /** Whether side a and side b have used their one time-out. */
  timeouts: [boolean, boolean]
  winner: Side | null
}

export type ErrorCode =
  | "already_started"
  | "invalid_start"
  | "not_in_progress"
  | "not_doubles"
  | "game_under_way"
  | "not_serving_pair"
  | "timeout_used"
  | "nothing_to_undo"
  | "unknown_event"

export class ScoringError extends Error {
  readonly code: ErrorCode

  constructor(code: ErrorCode) {
    super(code)
    this.code = code
  }
}

export const GAME_POINTS = 11
const PLAYERS: Player[] = ["a1", "a2", "b1", "b2"]

export const sideOf = (player: Player): Side => player[0] as Side
export const partnerOf = (player: Player): Player => `${player[0]}${player[1] === "1" ? "2" : "1"}` as Player
const index = (side: Side) => (side === "a" ? 0 : 1)
const otherEnd = (end: End | null): End | null => (end === null ? null : end === "left" ? "right" : "left")

/** Games a side must win: the majority of `best_of`. */
export const gamesNeeded = (config: Config) => Math.floor(config.best_of / 2) + 1

export function initialState(): State {
  return {
    status: "not_started",
    game_number: 1,
    games: [],
    games_won: [0, 0],
    points: [0, 0],
    server: null,
    receiver: null,
    first_server: null,
    first_receiver: null,
    a_end: null,
    decider_changed: false,
    timeouts: [false, false],
    winner: null,
  }
}

function copy(state: State): State {
  return {
    ...state,
    games: state.games.map((game) => [game[0], game[1]]),
    games_won: [state.games_won[0], state.games_won[1]],
    points: [state.points[0], state.points[1]],
    timeouts: [state.timeouts[0], state.timeouts[1]],
  }
}

function start(config: Config, state: State, event: Extract<ScoreEvent, { type: "start" }>): State {
  if (state.status !== "not_started") throw new ScoringError("already_started")
  if (!PLAYERS.includes(event.server) || (event.a_end !== "left" && event.a_end !== "right")) throw new ScoringError("invalid_start")
  let receiver: Player
  if (config.doubles) {
    // 2.13.4: in the first game the receiving pair decides which of them receives first.
    if (event.receiver === undefined || !PLAYERS.includes(event.receiver) || sideOf(event.receiver) === sideOf(event.server)) throw new ScoringError("invalid_start")
    receiver = event.receiver
  } else {
    if (event.server[1] !== "1") throw new ScoringError("invalid_start")
    receiver = sideOf(event.server) === "a" ? "b1" : "a1"
    if (event.receiver !== undefined && event.receiver !== receiver) throw new ScoringError("invalid_start")
  }
  const next = copy(state)
  next.status = "in_progress"
  next.server = next.first_server = event.server
  next.receiver = next.first_receiver = receiver
  next.a_end = event.a_end
  return next
}

function point(config: Config, state: State, side: Side): State {
  if (state.status !== "in_progress") throw new ScoringError("not_in_progress")
  if (side !== "a" && side !== "b") throw new ScoringError("unknown_event")
  const next = copy(state)
  next.points[index(side)] += 1
  const [a, b] = next.points
  const lead = Math.abs(a - b)
  const most = Math.max(a, b)

  // 2.11.1: first to 11, unless both reach 10; then the first to lead by 2.
  if (most >= GAME_POINTS && lead >= 2) {
    next.games.push([a, b])
    next.games_won[index(side)] += 1
    next.points = [0, 0]
    if (next.games_won[index(side)] === gamesNeeded(config)) {
      // 2.12.1: the match is the best of an odd number of games.
      next.status = "completed"
      next.winner = side
      next.server = next.receiver = next.first_server = next.first_receiver = null
      return next
    }
    next.game_number += 1
    next.decider_changed = false
    // 2.13.7: start the next game at the other end. 2.13.6: who served first now receives first; in
    // doubles the first receiver is whoever served to the first server in the game before (2.13.4),
    // which for the previous first receiver is the previous first server.
    next.a_end = otherEnd(next.a_end)
    next.server = state.first_receiver
    next.receiver = state.first_server
    next.first_server = next.server
    next.first_receiver = next.receiver
    return next
  }

  // 2.13.3: service changes after every 2 points, and after every point once both have 10.
  if ((a >= 10 && b >= 10) || (a + b) % 2 === 0) {
    const server = next.server as Player
    const receiver = next.receiver as Player
    // 2.13.5: in doubles the previous receiver serves and the previous server's partner receives.
    next.server = receiver
    next.receiver = config.doubles ? partnerOf(server) : server
  }
  // 2.13.6-2.13.7: in the last possible game, when a side first reaches 5 the players change ends,
  // and in doubles the pair due to receive next changes its order of receiving.
  if (next.game_number === config.best_of && !next.decider_changed && most === 5) {
    next.decider_changed = true
    next.a_end = otherEnd(next.a_end)
    if (config.doubles) next.receiver = partnerOf(next.receiver as Player)
  }
  return next
}

function chooseServer(config: Config, state: State, player: Player): State {
  if (!config.doubles) throw new ScoringError("not_doubles")
  if (state.status !== "in_progress") throw new ScoringError("not_in_progress")
  // The first game's server is set at the start; later the choice is made before the first point.
  if (state.game_number === 1 || state.points[0] + state.points[1] !== 0) throw new ScoringError("game_under_way")
  const server = state.server as Player
  if (!PLAYERS.includes(player) || sideOf(player) !== sideOf(server)) throw new ScoringError("not_serving_pair")
  const next = copy(state)
  if (player !== server) {
    // 2.13.4: the receiver is whoever served to the chosen server in the game before, which is the
    // partner of the player who would otherwise have received.
    next.server = next.first_server = player
    next.receiver = next.first_receiver = partnerOf(state.receiver as Player)
  }
  return next
}

function timeout(state: State, side: Side): State {
  if (state.status !== "in_progress") throw new ScoringError("not_in_progress")
  if (side !== "a" && side !== "b") throw new ScoringError("unknown_event")
  // 3.4.4.2: one time-out for each player or pair in an individual match.
  if (state.timeouts[index(side)]) throw new ScoringError("timeout_used")
  const next = copy(state)
  next.timeouts[index(side)] = true
  return next
}

/** The state after one event that isn't an undo. Throws ScoringError when the event isn't allowed. */
export function apply(config: Config, state: State, event: ScoreEvent): State {
  switch (event.type) {
    case "start":
      return start(config, state, event)
    case "point":
      return point(config, state, event.side)
    case "choose_server":
      return chooseServer(config, state, event.player)
    case "timeout":
      return timeout(state, event.side)
    default:
      throw new ScoringError("unknown_event")
  }
}

/**
 * A match being scored: the state now, and the states an undo goes back to. `push` returns a new
 * Scoring and leaves this one as it was, so a refused event changes nothing.
 */
export class Scoring {
  readonly config: Config
  readonly state: State
  private readonly earlier: readonly State[]

  constructor(config: Config, state: State = initialState(), earlier: readonly State[] = []) {
    this.config = config
    this.state = state
    this.earlier = earlier
  }

  /** How many actions an undo can still take back. */
  get undoable(): number {
    return this.earlier.length
  }

  push(event: ScoreEvent): Scoring {
    if (event.type === "undo") {
      if (this.earlier.length === 0) throw new ScoringError("nothing_to_undo")
      return new Scoring(this.config, this.earlier[this.earlier.length - 1], this.earlier.slice(0, -1))
    }
    return new Scoring(this.config, apply(this.config, this.state, event), [...this.earlier, this.state])
  }
}

/** The state after every event of a stream, in order. Throws on the first event that isn't allowed. */
export function replay(config: Config, events: readonly ScoreEvent[]): State[] {
  let scoring = new Scoring(config)
  return events.map((event) => {
    scoring = scoring.push(event)
    return scoring.state
  })
}
