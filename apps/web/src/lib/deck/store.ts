// The scoring deck's session (REQ-012, REQ-013), outside React and free of app imports so it can be
// tested under Node. The umpire's action is checked by the shared reducer, written to the journal, and
// only then shown. Events go to the server in order; the server replays them itself and is the
// authority. Whatever happens to the tab or the connection, an action the deck has shown is on the
// device until the server holds it.
import { Scoring, ScoringError, type Config, type ScoreEvent, type State } from "../../../../../packages/scoring/src/index.ts"
import { JournalError, type Journal, type JournalEvent } from "./journal.ts"

/** The sheet as the server gives it: what the session needs of it. */
export interface Sheet {
  id: string
  assignment_id: string
  revision: number
  config: unknown
  events: { id: string; sequence: number; event: unknown }[]
  confirmed_at?: string | null
}

export type Envelope = { id: string; sequence: number; event: ScoreEvent; device_time: string; expected_revision: number }

export interface Reply {
  revision: number
  refused: { sequence: number; code: string } | null
}

/** How the session reaches the server. `send` and `load` reject with whatever `classify` understands. */
export interface Transport<C extends Sheet> {
  load(scorecardId: string): Promise<C>
  send(card: C, events: Envelope[]): Promise<Reply>
  /**
   * What a rejection means: "gone" (the sheet isn't this umpire's any more), "stale" (this device's
   * assignment was replaced), "refused" (the server won't take it as it stands), anything else is
   * "offline" (no answer, or the server is unwell: try again later).
   */
  classify(error: unknown): { kind: "gone" | "stale" | "refused" | "offline"; message?: string }
}

export type Sync = "saved" | "sending" | "waiting"

export interface DeckView<C extends Sheet> {
  card?: C
  state?: State
  /** Every event that stands, accepted or still to be sent, in order: what the log is made from. */
  stream: { sequence: number; event: ScoreEvent }[]
  /** How many actions an undo can still take back. */
  undoable: number
  /** Actions on this device that the server hasn't acknowledged yet. */
  pending: number
  sync: Sync
  /** The sheet came from this device's copy because the server couldn't be reached. */
  offline: boolean
  /** Another tab is scoring this match: this one only watches. */
  readOnly: boolean
  /** Actions scored here that the server didn't accept and that were kept for review. */
  conflicts: number
  /** Why the last action wasn't taken, a refusal code of the rules or a sentence. */
  problem: string
  /** The device couldn't write: nothing more is shown as scored until it can. */
  storageFailed: boolean
  /** Why the sheet couldn't be opened at all. */
  failure: unknown
  /** The sheet is no longer this umpire's. */
  lost: boolean
}

export const MAX_BATCH = 200
export const HEARTBEAT_MS = 3_000

type Session<C extends Sheet> = {
  card: C
  scoring: Scoring
  stream: { sequence: number; event: ScoreEvent }[]
  queue: Envelope[]
}

const empty = <C extends Sheet>(): DeckView<C> => ({
  stream: [],
  undoable: 0,
  pending: 0,
  sync: "saved",
  offline: false,
  readOnly: false,
  conflicts: 0,
  problem: "",
  storageFailed: false,
  failure: null,
  lost: false,
})

const envelope = (kept: JournalEvent<ScoreEvent>): Envelope => ({ id: kept.id, sequence: kept.sequence, event: kept.event, device_time: kept.device_time, expected_revision: kept.expectedRevision })

export interface DeckOptions<C extends Sheet> {
  scorecardId: string
  userId: string
  transport: Transport<C>
  /** Opens the journal; rejects where the device has no usable storage. */
  openJournal: () => Promise<Journal>
  newId: () => string
  /** This tab's id; a promise where finding it takes a moment (the browser checks it is unique). */
  tabId: string | Promise<string>
  now?: () => number
}

export class DeckStore<C extends Sheet> {
  private session: Session<C> | null = null
  private journal: Journal | null = null
  private view: DeckView<C> = empty()
  private flushing: Promise<void> | null = null
  private readonly listeners = new Set<() => void>()
  /** Actions are taken one after another, each waiting for the journal before the next is looked at. */
  private chain: Promise<void> = Promise.resolve()
  private readonly options: DeckOptions<C>
  private tabId = ""

  constructor(options: DeckOptions<C>) {
    this.options = options
    if (typeof options.tabId === "string") this.tabId = options.tabId
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  snapshot = () => this.view

  private show(change: Partial<DeckView<C>> = {}) {
    const session = this.session
    this.view = {
      ...this.view,
      ...change,
      card: session?.card,
      state: session?.scoring.state,
      stream: session?.stream ?? [],
      undoable: session?.scoring.undoable ?? 0,
      pending: session?.queue.length ?? 0,
    }
    for (const listener of this.listeners) listener()
  }

  private get sheetKey() {
    const card = this.session?.card
    return { scorecardId: this.options.scorecardId, userId: this.options.userId, assignmentId: card?.assignment_id ?? "", revision: card?.revision ?? 0 }
  }

  /** Open the journal, take the sheet for this tab if no other tab has it, and load it. */
  open = async () => {
    this.tabId = await this.options.tabId
    try {
      this.journal = await this.options.openJournal()
      const mine = await this.journal.claim(this.options.scorecardId, this.tabId, this.options.now?.())
      this.show({ readOnly: !mine })
    } catch {
      // No storage on this device: the deck can still show the match, but can't promise to keep a point.
      this.journal = null
      this.show({ storageFailed: true })
    }
    await this.load()
  }

  /** Renew this tab's claim on the sheet; a tab that was watching takes over once the other has gone. */
  heartbeat = async () => {
    if (!this.journal) return
    try {
      const mine = await this.journal.claim(this.options.scorecardId, this.tabId, this.options.now?.())
      if (mine === this.view.readOnly) {
        this.show({ readOnly: !mine })
        if (mine) await this.load() // taking over: start from what the journal and the server hold now
      }
    } catch {
      // A missed beat is not a failure to score; the next write checks ownership again.
    }
  }

  close = async () => {
    const journal = this.journal
    this.journal = null
    try {
      await journal?.release(this.options.scorecardId, this.tabId)
    } catch {
      // The claim goes stale by itself.
    }
    journal?.close()
  }

  private build(card: C, extra: JournalEvent<ScoreEvent>[]): Session<C> {
    let scoring = new Scoring(card.config as Config)
    const stream = card.events.map((sent) => ({ sequence: sent.sequence, event: sent.event as ScoreEvent }))
    for (const { event } of stream) scoring = scoring.push(event)
    const queue: Envelope[] = []
    let next = card.revision + 1
    for (const kept of extra) {
      // Only an unbroken run after the card goes on: a gap or an event the rules now refuse ends it.
      if (kept.sequence !== next) break
      try {
        scoring = scoring.push(kept.event)
      } catch (error) {
        if (!(error instanceof ScoringError)) throw error
        break
      }
      stream.push({ sequence: kept.sequence, event: kept.event })
      queue.push(envelope(kept))
      next += 1
    }
    return { card, scoring, stream, queue }
  }

  /**
   * Take the sheet as the server holds it and put this device's unsent actions back on top of it. If
   * the server can't be reached, open from the device's own copy. Run on opening, on reconnecting and
   * on coming back to the tab, before anything new is written.
   *
   * Asking the server takes time and the umpire may tap meanwhile. So the answer is merged with the
   * journal in the same queue as the umpire's actions: an action is either fully taken before the
   * merge reads the journal, or waits until the merge is done. No tap falls between the two.
   */
  load = async () => {
    const { scorecardId, transport } = this.options
    let card: C | null = null
    let failure: unknown = null
    try {
      card = await transport.load(scorecardId)
    } catch (error) {
      failure = error
    }
    this.chain = this.chain.then(() => this.merge(card, failure)).catch((error: unknown) => this.show({ failure: error }))
    await this.chain
  }

  private async merge(card: C | null, failure: unknown) {
    const { scorecardId, userId, transport } = this.options
    const journal = this.journal
    let kept: { sheet: { card: C; revision: number; acked: number } | null; events: JournalEvent<ScoreEvent>[] } = { sheet: null, events: [] }
    try {
      if (journal) kept = await journal.read<C, ScoreEvent>(scorecardId, userId)
    } catch {
      this.show({ storageFailed: true })
    }

    if (!card) {
      const { kind } = transport.classify(failure)
      if (kind === "offline" && kept.sheet) {
        // The server can't be reached: carry on from what this device holds.
        const local = kept.events.filter((event) => event.sequence > kept.sheet!.card.revision)
        this.session = this.build(kept.sheet.card, local)
        this.session.queue = this.session.queue.filter((sent) => sent.sequence > kept.sheet!.acked)
        this.show({ offline: true, failure: null, sync: this.session.queue.length ? "waiting" : "saved", conflicts: await this.countConflicts() })
        return
      }
      if (this.session) this.session.queue = []
      this.show(kind === "gone" ? { lost: true, conflicts: await this.countConflicts() } : { failure })
      return
    }

    // The server answered. What this device wrote after the server's revision is still to be sent, as
    // long as it was written under the assignment the sheet has now and follows on without a gap.
    const ahead = kept.events.filter((event) => event.sequence > card.revision)
    // If the server holds somebody else's event where this device wrote one it never had accepted,
    // the stream went on elsewhere: nothing this device wrote from there on can follow it.
    const theirs = new Map(card.events.map((sent) => [sent.sequence, sent.id]))
    const acked = kept.sheet?.acked ?? 0
    const diverged = kept.events.find((event) => event.sequence > acked && event.sequence <= card.revision && theirs.get(event.sequence) !== event.id)
    const usable = diverged || card.confirmed_at ? [] : ahead.filter((event) => event.assignmentId === card.assignment_id)
    const session = this.build(card, usable)
    try {
      // Only the tab that owns the sheet tidies the journal; a tab that is watching just shows it.
      if (journal && !this.view.readOnly) {
        if (diverged || ahead.length > session.queue.length) {
          // Scored here but no longer sendable (reassigned, or the stream moved on elsewhere): kept, visible, never sent.
          const from = diverged ? diverged.sequence : session.queue.length ? session.queue[session.queue.length - 1].sequence + 1 : card.revision + 1
          await journal.setAside(scorecardId, userId, from)
        }
        await journal.saveSheet({ scorecardId, userId, card, revision: card.revision })
      }
    } catch {
      this.show({ storageFailed: true })
    }
    this.session = session
    this.show({ offline: false, failure: null, lost: false, sync: session.queue.length ? "waiting" : "saved", conflicts: await this.countConflicts() })
    if (session.queue.length) void this.flush()
  }

  private async countConflicts() {
    try {
      return (await this.journal?.conflicts(this.options.scorecardId, this.options.userId))?.length ?? 0
    } catch {
      return this.view.conflicts
    }
  }

  /** The umpire has seen the conflicts and lets them go. */
  dismissConflicts = async () => {
    try {
      await this.journal?.clearConflicts(this.options.scorecardId, this.options.userId)
      this.show({ conflicts: 0 })
    } catch {
      this.show({ storageFailed: true })
    }
  }

  /**
   * Take one action. It is shown only after the journal has committed it: if the device can't write,
   * the deck says so and the score stays where it was. Resolves when the action has been dealt with.
   */
  act = (event: ScoreEvent): Promise<void> => {
    // A failure inside one action must not stop the ones after it from being looked at.
    this.chain = this.chain.then(() => this.take(event)).catch(() => this.show({ problem: "storage", storageFailed: true }))
    return this.chain
  }

  private async take(event: ScoreEvent) {
    const session = this.session
    const view = this.view
    if (!session || view.lost || view.failure || session.card.confirmed_at) return
    if (view.readOnly) return this.show({ problem: "read_only" })
    let next: Scoring
    try {
      next = session.scoring.push(event)
    } catch (error) {
      if (!(error instanceof ScoringError)) throw error
      return this.show({ problem: error.code })
    }
    if (next === session.scoring) return // changed nothing, so there is nothing to keep or send
    if (!this.journal) return this.show({ storageFailed: true, problem: "storage" })
    let written: JournalEvent<ScoreEvent>
    try {
      const now = this.options.now?.() ?? Date.now()
      written = await this.journal.append(this.sheetKey, this.tabId, () => ({ id: this.options.newId(), event, device_time: new Date(now).toISOString() }), now)
    } catch (error) {
      if (error instanceof JournalError && error.code === "not_owner") return this.show({ readOnly: true, problem: "read_only" })
      // Not saved, so not scored: the umpire is told before anything changes on screen.
      return this.show({ storageFailed: true, problem: "storage" })
    }
    session.scoring = next
    session.stream = [...session.stream, { sequence: written.sequence, event }]
    session.queue = [...session.queue, envelope(written)]
    this.show({ problem: "", storageFailed: false })
    void this.flush()
  }

  /**
   * Send what is queued, in order, one request at a time, until the queue is empty. Called after
   * every action, on reconnecting, on coming back to the tab, on a timer and by the umpire's Retry.
   * While a round is under way, callers get that round: there is never more than one.
   */
  flush = (): Promise<void> => {
    this.flushing ??= this.send().finally(() => {
      this.flushing = null
    })
    return this.flushing
  }

  private async send() {
    const { transport, scorecardId, userId } = this.options
    try {
      // A tab that slept may have lost the sheet to another: ask before sending anything.
      if (this.journal && !(await this.journal.claim(scorecardId, this.tabId, this.options.now?.()))) return this.show({ readOnly: true })
      for (;;) {
        const session = this.session
        if (!session || session.queue.length === 0 || this.view.lost || this.view.readOnly) break
        this.show({ sync: "sending" })
        const reply = await transport.send(session.card, session.queue.slice(0, MAX_BATCH))
        if (this.session !== session) continue // reloaded meanwhile: go on from what it holds now
        session.queue = session.queue.filter((sent) => sent.sequence > reply.revision)
        session.card = { ...session.card, revision: reply.revision }
        await this.journal?.markAcked(scorecardId, userId, reply.revision).catch(() => undefined)
        if (reply.refused) {
          // Whatever the reason (another writer's event in its place, or the server's rules), it and
          // what followed can't join the stream. They are set aside, visible, never sent again.
          try {
            await this.journal?.setAside(scorecardId, userId, reply.refused.sequence)
          } catch {
            // If they can't be set aside they would be sent again and again: stop until the device can write.
            session.queue = []
            this.show({ storageFailed: true, failure: new Error("storage") })
            break
          }
          await this.load()
          if (!this.view.failure && !this.view.lost) this.show({ problem: `refused:${reply.refused.code}` })
          break
        }
        this.show({ offline: false })
      }
      if (!this.view.failure && !this.view.lost && !this.session?.queue.length) this.show({ sync: "saved" })
    } catch (error) {
      const { kind, message } = transport.classify(error)
      if (kind === "offline") this.show({ sync: "waiting" }) // nothing is lost: it is all in the journal
      else if (kind === "gone") {
        // Not ours any more. What this device scored and couldn't send stays on it, marked.
        await this.journal?.setAside(scorecardId, userId, (this.session?.card.revision ?? 0) + 1).catch(() => undefined)
        if (this.session) this.session.queue = []
        this.show({ lost: true, conflicts: await this.countConflicts() })
      } else {
        // Reassigned or otherwise refused as a whole: a reread decides what can still be sent. What is
        // still queued afterwards waits for the next round (a retry, the timer), not a tight loop.
        await this.load()
        if (!this.view.failure && !this.view.lost) this.show({ sync: this.session?.queue.length ? "waiting" : "saved", problem: message ?? `refused:${kind}` })
      }
    }
  }
}
