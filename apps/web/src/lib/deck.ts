// The scoring deck's session (REQ-012): the score the umpire sees comes from the shared reducer at once,
// every action is sent to the server in order, and what the server holds is the authority. The server
// replays each event itself; if it refuses one, the deck goes back to what the server has.
import { useEffect, useState, useSyncExternalStore } from "react"
import { Scoring, ScoringError, type ScoreEvent, type State } from "@scoring"
import { ApiError } from "@/lib/api"
import { configOf, getScorecard, MAX_BATCH, namesOf, REFUSAL, sendEvents, type Envelope, type Names, type Scorecard } from "@/lib/scoring"

export type Sync = "saved" | "sending" | "waiting"

export type LogLine = { sequence: number; text: string }

type Session = {
  card: Scorecard
  scoring: Scoring
  /** Every event that stands in the stream, accepted or still on its way, in order. */
  stream: { sequence: number; event: ScoreEvent }[]
  /** Events the server hasn't acknowledged yet. */
  queue: Envelope[]
}

function build(card: Scorecard): Session {
  let scoring = new Scoring(configOf(card))
  const stream = card.events.map((sent) => ({ sequence: sent.sequence, event: sent.event as ScoreEvent }))
  for (const { event } of stream) scoring = scoring.push(event)
  return { card, scoring, stream, queue: [] }
}

const newId = () => (typeof crypto.randomUUID === "function" ? crypto.randomUUID() : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => (Number(c) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))).toString(16)))

/** What happened, in words, from the events alone: no shot is ever described (REQ-018). */
export function describeLog(card: Scorecard, stream: Session["stream"], names: Names): LogLine[] {
  let scoring = new Scoring(configOf(card))
  const lines: LogLine[] = []
  for (const { sequence, event } of stream) {
    const before = scoring.state
    scoring = scoring.push(event)
    const after = scoring.state
    lines.push({ sequence, text: describe(event, before, after, names) })
  }
  return lines.reverse()
}

function describe(event: ScoreEvent, before: State, after: State, names: Names): string {
  switch (event.type) {
    case "start":
      return `Match started. ${names[event.server]} serves first.`
    case "point": {
      // Scores read from the side that won the point, so "3–0" never depends on which side is a.
      const who = names[event.side]
      const mine = <T>(pair: readonly [T, T]) => (event.side === "a" ? pair : ([pair[1], pair[0]] as const)).join("–")
      if (after.games.length > before.games.length) {
        const tail = after.status === "completed" ? ` Match to ${who}, ${mine(after.games_won)}.` : ""
        return `Point and game ${after.games.length} to ${who}, ${mine(after.games[after.games.length - 1])}.${tail}`
      }
      return `Point to ${who}: ${mine(after.points)}.`
    }
    case "choose_server":
      return after === before ? `${names[event.player]} already serves first.` : `${names[event.player]} serves first in game ${after.game_number}.`
    case "timeout":
      return `Time-out: ${names[event.side]}.`
    case "undo":
      return "Undo: the last action was taken back."
  }
}

export type DeckView = {
  card?: Scorecard
  state?: State
  /** How many actions an undo can still take back. */
  undoable: number
  log: LogLine[]
  /** Actions the server hasn't acknowledged yet. */
  pending: number
  sync: Sync
  /** Why the last action wasn't taken, in the umpire's words. */
  problem: string
  /** Why the sheet couldn't be loaded. */
  failure: unknown
  /** The sheet is no longer this umpire's: reassigned, or it never was. */
  lost: boolean
}

const EMPTY: DeckView = { undoable: 0, log: [], pending: 0, sync: "saved", problem: "", failure: null, lost: false }

/**
 * One sheet being scored, outside React so that actions, the send queue and replies from the server
 * are handled in order whatever is on screen. `act` applies an action at once and queues it.
 */
export class DeckStore {
  private session: Session | null = null
  private sending = false
  private view: DeckView = EMPTY
  private readonly listeners = new Set<() => void>()
  private readonly scorecardId: string

  constructor(scorecardId: string) {
    this.scorecardId = scorecardId
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  snapshot = () => this.view

  private show(change: Partial<DeckView> = {}) {
    const session = this.session
    this.view = {
      ...this.view,
      ...change,
      card: session?.card,
      state: session?.scoring.state,
      undoable: session?.scoring.undoable ?? 0,
      log: session ? describeLog(session.card, session.stream, namesOf(session.card)) : [],
      pending: session?.queue.length ?? 0,
    }
    for (const listener of this.listeners) listener()
  }

  /** Take the sheet as the server holds it. Anything queued and not yet accepted is given up. */
  load = async () => {
    try {
      this.session = build(await getScorecard(this.scorecardId))
      this.show({ failure: null, sync: "saved" })
    } catch (error) {
      // Without the server's copy there is nothing sure to show: the deck stops until it loads.
      if (this.session) this.session.queue = []
      this.show(error instanceof ApiError && error.status === 404 ? { lost: true } : { failure: error })
    }
  }

  act = (event: ScoreEvent) => {
    const session = this.session
    if (!session || this.view.lost || this.view.failure) return
    try {
      const next = session.scoring.push(event)
      if (next === session.scoring) return // changed nothing, so there is nothing to send
      const sequence = (session.stream.at(-1)?.sequence ?? 0) + 1
      session.scoring = next
      session.stream = [...session.stream, { sequence, event }]
      session.queue = [...session.queue, { id: newId(), sequence, event, device_time: new Date().toISOString() }]
      this.show({ problem: "" })
    } catch (error) {
      if (!(error instanceof ScoringError)) throw error
      this.show({ problem: REFUSAL[error.code] ?? "That isn't allowed right now." })
      return
    }
    void this.flush()
  }

  /**
   * Send what is queued, in order, one request at a time, until the queue is empty. Actions taken
   * while a request is on its way join the queue and go with the next one. If the server refuses
   * something, the deck goes back to what the server holds: actions not yet accepted, including any
   * tapped in the meantime, are given up and the umpire is told.
   */
  flush = async () => {
    if (this.sending) return
    this.sending = true
    try {
      for (;;) {
        const session = this.session
        if (!session || session.queue.length === 0 || this.view.lost) break
        this.show({ sync: "sending" })
        // After a long break the queue can be longer than one request takes: it goes in parts.
        const reply = await sendEvents(session.card.id, session.card.assignment_id, session.queue.slice(0, MAX_BATCH))
        if (this.session !== session) continue // the sheet was reloaded meanwhile: start from what it holds now
        if (reply.refused) {
          await this.resync(`The server didn't take the last action. ${REFUSAL[reply.refused.code] ?? ""}`)
          break
        }
        session.queue = session.queue.filter((sent) => sent.sequence > reply.revision)
        session.card = { ...session.card, revision: reply.revision }
      }
      if (!this.view.failure && !this.view.lost) this.show({ sync: "saved" })
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.code === "stale_assignment")) this.show({ lost: true })
      else if (error instanceof ApiError && error.status < 500) await this.resync(error.serverMessage ?? "The server didn't take the last action.")
      else this.show({ sync: "waiting" }) // offline or a server hiccup: the actions stay queued for a retry
    } finally {
      this.sending = false
    }
  }

  private async resync(why: string) {
    await this.load()
    if (!this.view.failure && !this.view.lost) this.show({ problem: `${why} The score shown is what is saved; anything after it was not kept.` })
  }
}

/** The deck for one sheet: what to show, and `act`, `retry` and `reload` to change it. */
export function useDeck(scorecardId: string) {
  const [store] = useState(() => new DeckStore(scorecardId))
  const view = useSyncExternalStore(store.subscribe, store.snapshot)
  useEffect(() => {
    void store.load()
  }, [store])
  return { ...view, act: store.act, retry: store.flush, reload: store.load }
}
