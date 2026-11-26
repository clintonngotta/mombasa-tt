// The scoring deck for React (REQ-012, REQ-013): the session and the journal live in lib/deck/, which
// knows nothing of the app; this file gives them the API, the browser's events and words for the umpire.
import { useEffect, useState, useSyncExternalStore } from "react"
import { Scoring, type ScoreEvent, type State } from "@scoring"
import { ApiError } from "@/lib/api"
import { Journal } from "@/lib/deck/journal"
import { DeckStore, HEARTBEAT_MS, type DeckView, type Transport } from "@/lib/deck/store"
import { CARD_REASON_LABEL, configOf, getScorecard, REFUSAL, reportConflict, sendEvents, takeDevice, type Names, type Scorecard } from "@/lib/scoring"

export type { Sync } from "@/lib/deck/store"

export type LogLine = { sequence: number; text: string }

type Stream = DeckView<Scorecard>["stream"]

const newId = () => (typeof crypto.randomUUID === "function" ? crypto.randomUUID() : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => (Number(c) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))).toString(16)))

/** What happened, in words, from the events alone: no shot is ever described (REQ-018). */
export function describeLog(card: Scorecard, stream: Stream, names: Names): LogLine[] {
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
    case "timeout_end":
      return "Time-out over: play resumes."
    case "card": {
      const given = after.offences[event.player] // one up the ladder from the player's or the pair's count
      const points = given - 1
      const shown = given === 1 ? "Yellow card" : `Yellow and red card, ${points} penalty point${points === 1 ? "" : "s"}`
      return `${shown}: ${names[event.player]} (${(CARD_REASON_LABEL[event.reason] ?? event.reason).toLowerCase()}).${event.note ? ` ${event.note}` : ""}`
    }
    case "adviser_card": {
      const index = event.side === "a" ? 0 : 1
      return `${after.advisers[index] === 1 ? "Yellow card" : "Red card, sent away"}: ${names[event.side]}'s adviser (${(CARD_REASON_LABEL[event.reason] ?? event.reason).toLowerCase()}).`
    }
    case "suspension":
      return `Play suspended: ${names[event.side]} injured.`
    case "suspension_end":
      return "Suspension over: play resumes."
    case "expedite":
      return "Expedite system started: service changes every point."
    case "retire":
      return `${names[event.side]} retired. Match to ${names[event.side === "a" ? "b" : "a"]}.`
    case "disqualify":
      return `${names[event.side]} disqualified by the referee. Match to ${names[event.side === "a" ? "b" : "a"]}.`
    case "undo":
      return "Undo: the last action was taken back."
  }
}

const TAB_KEY = "coast-tt-tab"

/**
 * This tab's id for owning a sheet. It is kept for the life of the tab, so a reload is still the same
 * tab and takes its sheet back at once. A duplicated tab starts with a copy of it; the original, still
 * open, says so and the copy takes a new one.
 */
let identity: Promise<string> | null = null

/** Settled once per page load; the channel stays open to answer a duplicate of this tab. */
const tabIdentity = () => (identity ??= findTabIdentity())

function findTabIdentity(): Promise<string> {
  let id = ""
  try {
    id = sessionStorage.getItem(TAB_KEY) ?? ""
  } catch {
    // No session storage: every page load is a new tab, which only costs a short wait after a reload.
  }
  const keep = (value: string) => {
    try {
      sessionStorage.setItem(TAB_KEY, value)
    } catch {
      // as above
    }
    return value
  }
  if (typeof BroadcastChannel === "undefined") return Promise.resolve(keep(id || newId()))
  return new Promise((resolve) => {
    const channel = new BroadcastChannel(TAB_KEY)
    const settle = (value: string) => {
      channel.onmessage = (message) => {
        // From now on answer anybody who turns up with our id.
        if (message.data?.hello === value) channel.postMessage({ taken: value })
      }
      resolve(keep(value))
    }
    if (!id) return settle(newId())
    const wait = setTimeout(() => settle(id), 200)
    channel.onmessage = (message) => {
      if (message.data?.taken !== id) return
      clearTimeout(wait)
      settle(newId())
    }
    channel.postMessage({ hello: id })
  })
}

const transport: Transport<Scorecard> = {
  load: getScorecard,
  // Each event carries the server revision the device had seen when it was written (REQ-013).
  send: (card, events) => sendEvents(card.id, card.assignment_id, events),
  take: takeDevice,
  report: async (scorecardId, report) => void (await reportConflict(scorecardId, report)),
  classify(error) {
    if (error instanceof ApiError) {
      if (error.status === 404) return { kind: "gone" }
      // This version of the app is too old for the API (REQ-035): the actions are fine, the app isn't.
      // They wait in the journal, untouched, and the updated app sends them.
      if (error.status === 426) return { kind: "offline" }
      if (error.code === "stale_assignment") return { kind: "stale", message: error.serverMessage }
      if (error.status >= 400 && error.status < 500 && error.status !== 429) return { kind: "refused", message: error.serverMessage }
    }
    return { kind: "offline" } // no answer, a proxy page or a server error: the actions wait
  },
}

/** What stopped the last action, in the umpire's words. */
export function problemText(problem: string): string {
  if (!problem) return ""
  if (problem === "read_only") return "This match is open for scoring in another tab or window. Score it there, or close that one."
  if (problem === "not_reported") return "These actions haven't reached the organizers yet. They can be removed once the report has been sent."
  if (problem === "elsewhere") return "This match is being scored on another device. Take it over here to score from this one."
  if (problem === "offline_take_over") return "Taking the match over needs a connection to Coast TT."
  if (problem === "storage") return "This device couldn't save that action, so it was NOT scored. Free some storage or leave private browsing, then try again."
  if (problem.startsWith("refused:")) return `The server didn't take an action. ${REFUSAL[problem.slice(8)] ?? ""} The score shown is what the server holds; what it didn't take is listed above.`
  return REFUSAL[problem] ?? problem
}

/**
 * The deck for one sheet of one account: what to show, and `act`, `retry`, `reload` and
 * `dismissConflicts` to change it. The session is reread from the server and the device whenever the
 * connection comes back or the tab is looked at again, before anything new is written.
 */
export function useDeck(scorecardId: string, userId: string) {
  const [store] = useState(
    () =>
      new DeckStore<Scorecard>({
        scorecardId,
        userId,
        transport,
        openJournal: () => Journal.open(),
        newId,
        tabId: tabIdentity(),
      })
  )
  const view = useSyncExternalStore(store.subscribe, store.snapshot)

  useEffect(() => {
    void store.open()
    // Ask the browser not to clear this site's storage under pressure; it may say no.
    void navigator.storage?.persist?.().catch(() => false)
    const beat = setInterval(() => void store.heartbeat(), HEARTBEAT_MS)
    const retry = setInterval(() => void store.flush(), 15_000)
    const reread = () => {
      if (document.visibilityState === "visible") void store.load()
    }
    const leave = () => void store.close()
    window.addEventListener("online", reread)
    window.addEventListener("focus", reread)
    document.addEventListener("visibilitychange", reread)
    window.addEventListener("pagehide", leave)
    return () => {
      clearInterval(beat)
      clearInterval(retry)
      window.removeEventListener("online", reread)
      window.removeEventListener("focus", reread)
      document.removeEventListener("visibilitychange", reread)
      window.removeEventListener("pagehide", leave)
      void store.close()
    }
  }, [store])

  return { ...view, act: (event: ScoreEvent) => void store.act(event), retry: store.flush, reload: store.load, dismissConflicts: store.dismissConflicts, takeOver: store.takeOver }
}

/** How many of the account's score actions are on this device and not yet on the server. */
export async function unsentScoreActions(userId: string): Promise<number> {
  try {
    const journal = await Journal.open()
    try {
      return await journal.unsent(userId)
    } finally {
      journal.close()
    }
  } catch {
    return 0
  }
}

/**
 * Whether this device is in the middle of scoring (REQ-035): a match open on the deck in any tab, or
 * score actions of any account not yet on the server. A new version of the app waits until neither.
 */
export async function scoringOnDevice(): Promise<{ scoring: number; unsent: number }> {
  try {
    const journal = await Journal.open()
    try {
      return { scoring: await journal.scoringNow(), unsent: await journal.unsentOnDevice() }
    } finally {
      journal.close()
    }
  } catch {
    // No storage: nothing can be waiting on this device.
    return { scoring: 0, unsent: 0 }
  }
}

/** Remove the account's scoring records from this device. */
export async function purgeScoreJournal(userId: string): Promise<void> {
  try {
    const journal = await Journal.open()
    try {
      await journal.purge(userId)
    } finally {
      journal.close()
    }
  } catch {
    // Nothing kept, or no storage to clear.
  }
}
