// The score journal and the deck session (REQ-013, EVAL-013), run under Node with a stand-in IndexedDB:
//   node --experimental-strip-types --test test/deck.test.ts
// "The device" is one IDBFactory; "a tab" is a DeckStore with its own tab id; "the server" is a small
// model of the API's rules (order, retries, assignment) scoring with the same reducer.
import assert from "node:assert/strict"
import { test } from "node:test"
import { IDBFactory, IDBKeyRange as FakeKeyRange } from "fake-indexeddb"
import { Scoring, ScoringError, type ScoreEvent } from "../../../packages/scoring/src/index.ts"
import { Journal, JournalError, OWNER_STALE_MS } from "../src/lib/deck/journal.ts"
import { DeckStore, MAX_BATCH, type Envelope, type Reply, type Sheet, type Transport } from "../src/lib/deck/store.ts"

// The journal uses the global IDBKeyRange, as a browser provides it.
;(globalThis as { IDBKeyRange?: unknown }).IDBKeyRange = FakeKeyRange

const CONFIG = { best_of: 3, doubles: false } as const
const START: ScoreEvent = { type: "start", server: "a1", a_end: "left" }
const point = (side: "a" | "b"): ScoreEvent => ({ type: "point", side })

class Offline extends Error {}
class Gone extends Error {}
class Stale extends Error {}

/** The API as far as the deck is concerned. */
class Server {
  online = true
  /** Accept the next batch, then lose the reply (the request times out on the way back). */
  loseReply = false
  assignment = "assignment-1"
  mine = true
  /** Make `load` wait until the test lets it go, to act while the server is being asked. */
  gate: Promise<void> | null = null
  /** A rule the device's reducer doesn't have: the server takes no time-outs. */
  noTimeouts = false
  events: { id: string; sequence: number; event: ScoreEvent }[] = []
  requests = 0

  sheet(): Sheet {
    return { id: "sheet", assignment_id: this.assignment, revision: this.events.length, config: CONFIG, events: [...this.events] }
  }

  transport(): Transport<Sheet> {
    return {
      load: async () => {
        const sheet = this.online && this.mine ? this.sheet() : null // what the server held when asked
        if (this.gate) await this.gate
        if (sheet && this.online && this.mine) return sheet
        if (!this.online) throw new Offline()
        if (!this.mine) throw new Gone()
        return this.sheet()
      },
      send: async (card, events) => {
        if (!this.online) throw new Offline()
        this.requests += 1
        if (!this.mine) throw new Gone()
        if (card.assignment_id !== this.assignment) throw new Stale()
        assert.ok(events.length <= MAX_BATCH)
        const reply = this.accept(events)
        if (this.loseReply) {
          this.loseReply = false
          throw new Offline()
        }
        return reply
      },
      classify: (error) => ({ kind: error instanceof Gone ? "gone" : error instanceof Stale ? "stale" : "offline" }),
    }
  }

  private accept(events: Envelope[]): Reply {
    let scoring = new Scoring(CONFIG)
    for (const kept of this.events) scoring = scoring.push(kept.event)
    let refused: Reply["refused"] = null
    for (const sent of events) {
      const known = this.events.find((kept) => kept.id === sent.id)
      if (known?.sequence === sent.sequence) continue
      if (known || sent.sequence <= this.events.length) refused = { sequence: sent.sequence, code: "sequence_conflict" }
      else if (sent.sequence !== this.events.length + 1) refused = { sequence: sent.sequence, code: "sequence_gap" }
      else {
        try {
          if (this.noTimeouts && sent.event.type === "timeout") throw new ScoringError("timeout_used")
          assert.ok(sent.expected_revision <= this.events.length, "the device never claims to have seen more than the server holds")
          scoring = scoring.push(sent.event)
          this.events.push({ id: sent.id, sequence: sent.sequence, event: sent.event })
        } catch (error) {
          if (!(error instanceof ScoringError)) throw error
          refused = { sequence: sent.sequence, code: error.code }
        }
      }
      if (refused) break
    }
    return { revision: this.events.length, refused }
  }

  state() {
    let scoring = new Scoring(CONFIG)
    for (const kept of this.events) scoring = scoring.push(kept.event)
    return scoring.state
  }
}

let ids = 0
function tab(device: IDBFactory, server: Server, name: string, options: { userId?: string; now?: () => number; journal?: () => Promise<Journal> } = {}) {
  return new DeckStore<Sheet>({
    scorecardId: "sheet",
    userId: options.userId ?? "umpire",
    transport: server.transport(),
    openJournal: options.journal ?? (() => Journal.open(device)),
    newId: () => `event-${++ids}`,
    tabId: name,
    now: options.now,
  })
}

/** 100 legal actions: points for both sides with an undo now and then, never finishing a best of 3 early. */
function hundredActions(): ScoreEvent[] {
  const actions: ScoreEvent[] = [START]
  for (let n = 1; actions.length < 100; n++) actions.push(n % 9 === 0 ? { type: "undo" } : point(n % 2 ? "a" : "b"))
  return actions
}

test("an action is shown only after the journal has it, and a failed write is not a score", async () => {
  const device = new IDBFactory()
  const server = new Server()
  let failing = false
  const journal = async () => {
    const real = await Journal.open(device)
    const append = real.append.bind(real)
    real.append = ((...args: Parameters<typeof append>) => (failing ? Promise.reject(new JournalError("storage", { name: "QuotaExceededError" })) : append(...args))) as typeof real.append
    return real
  }
  const deck = tab(device, server, "tab-1", { journal })
  await deck.open()
  await deck.act(START)
  await deck.act(point("a"))
  assert.deepEqual(deck.snapshot().state?.points, [1, 0])

  failing = true
  await deck.act(point("a"))
  const view = deck.snapshot()
  assert.deepEqual(view.state?.points, [1, 0], "the score didn't move")
  assert.equal(view.storageFailed, true)
  assert.equal(view.problem, "storage")
  await deck.flush()
  assert.equal(server.events.length, 2, "nothing unsaved was sent")

  failing = false
  await deck.act(point("a"))
  await deck.flush()
  assert.equal(deck.snapshot().storageFailed, false)
  assert.deepEqual(server.state().points, [2, 0])
})

test("a device with no storage shows the match but scores nothing", async () => {
  const server = new Server()
  const deck = tab(new IDBFactory(), server, "tab-1", { journal: () => Promise.reject(new JournalError("storage")) })
  await deck.open()
  await deck.act(START)
  assert.equal(deck.snapshot().state?.status, "not_started")
  assert.equal(deck.snapshot().storageFailed, true)
  assert.equal(server.events.length, 0)
})

test("100 actions offline survive closing and reopening twice and are accepted once, in order", async () => {
  const device = new IDBFactory()
  const server = new Server()
  let deck = tab(device, server, "tab-1")
  await deck.open() // the sheet is downloaded while connected
  server.online = false

  const actions = hundredActions()
  for (const action of actions.slice(0, 40)) await deck.act(action)
  assert.equal(deck.snapshot().pending, 40)
  assert.equal(deck.snapshot().sync, "waiting")
  await deck.close()

  deck = tab(device, server, "tab-2") // the browser was closed and opened again, still offline
  await deck.open()
  assert.equal(deck.snapshot().offline, true)
  assert.equal(deck.snapshot().pending, 40)
  for (const action of actions.slice(40, 80)) await deck.act(action)
  await deck.close()

  deck = tab(device, server, "tab-3")
  await deck.open()
  for (const action of actions.slice(80)) await deck.act(action)
  const local = deck.snapshot()
  assert.equal(local.pending, 100)
  assert.deepEqual(local.stream.map((kept) => kept.sequence), Array.from({ length: 100 }, (_, n) => n + 1))
  assert.equal(server.events.length, 0)

  // Back online: one retry sends everything, and the server arrives at the same state.
  server.online = true
  server.loseReply = true // the first reply is lost: the retry must not double anything
  await deck.flush()
  assert.equal(deck.snapshot().sync, "waiting")
  await deck.flush()
  const sent = deck.snapshot()
  assert.equal(sent.pending, 0)
  assert.equal(sent.sync, "saved")
  assert.equal(server.events.length, 100)
  assert.deepEqual(server.events.map((kept) => kept.event), actions)
  assert.equal(new Set(server.events.map((kept) => kept.id)).size, 100, "every event once")
  assert.deepEqual(server.state(), local.state)
  const journal = await Journal.open(device)
  assert.equal(await journal.unsent("umpire"), 0)
})

test("a queue longer than one request goes in parts", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const deck = tab(device, server, "tab-1")
  await deck.open()
  server.online = false
  await deck.act(START)
  // Undo and redo a point: 2 events each time, never ending the match.
  for (let n = 0; n < 150; n++) {
    await deck.act(point("a"))
    await deck.act({ type: "undo" })
  }
  server.online = true
  server.requests = 0
  await deck.flush()
  assert.equal(server.events.length, 301)
  assert.equal(server.requests, 2)
  assert.equal(deck.snapshot().sync, "saved")
})

test("one tab writes: a second tab only watches, and takes over when the first has gone", async () => {
  const device = new IDBFactory()
  const server = new Server()
  let clock = 1_000_000
  const now = () => clock
  const first = tab(device, server, "tab-1", { now })
  const second = tab(device, server, "tab-2", { now })
  await first.open()
  await second.open()
  assert.equal(first.snapshot().readOnly, false)
  assert.equal(second.snapshot().readOnly, true)

  await first.act(START)
  await second.act(START)
  assert.equal(second.snapshot().problem, "read_only")
  await second.act(point("b"))
  await first.flush()
  assert.equal(server.events.length, 1, "only the owner's action exists")

  // The first tab stops renewing its claim (closed without saying so); the second takes over.
  clock += OWNER_STALE_MS + 1
  await second.heartbeat()
  assert.equal(second.snapshot().readOnly, false)
  assert.equal(second.snapshot().state?.status, "in_progress", "it starts from what is saved")
  await second.act(point("b"))
  await second.flush()
  assert.deepEqual(server.state().points, [0, 1])
  // The first tab comes back: its write is refused inside the journal's transaction, not after it.
  await first.act(point("a"))
  assert.equal(first.snapshot().readOnly, true)
  await first.flush()
  assert.deepEqual(server.state().points, [0, 1])
})

test("after a reassignment, what this device couldn't send is kept as a conflict and never sent", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const deck = tab(device, server, "tab-1")
  await deck.open()
  await deck.act(START)
  await deck.flush()
  server.online = false
  await deck.act(point("a"))
  await deck.act(point("a"))

  // Meanwhile the organizers reassign the match and somebody else scores a point.
  server.assignment = "assignment-2"
  server.events.push({ id: "theirs", sequence: 2, event: point("b") })
  server.online = true
  await deck.flush()
  const view = deck.snapshot()
  assert.equal(view.conflicts, 2)
  assert.equal(view.pending, 0)
  assert.deepEqual(view.state?.points, [0, 1], "the deck shows what the server holds")
  assert.deepEqual(server.events.map((kept) => kept.id), [server.events[0].id, "theirs"], "nothing was overwritten")
  const journal = await Journal.open(device)
  assert.equal((await journal.conflicts("sheet", "umpire")).length, 2)
  assert.equal(await journal.unsent("umpire"), 2, "conflicts count as not being on the server")

  // Scoring goes on under the new assignment from the server's stream.
  await deck.act(point("a"))
  await deck.flush()
  assert.deepEqual(server.state().points, [1, 1])
  await deck.dismissConflicts()
  assert.equal(deck.snapshot().conflicts, 0)
  assert.equal(await journal.unsent("umpire"), 0)
})

test("a sheet taken away keeps the unsent actions on the device", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const deck = tab(device, server, "tab-1")
  await deck.open()
  await deck.act(START)
  await deck.flush()
  server.online = false
  await deck.act(point("a"))
  server.online = true
  server.mine = false
  await deck.flush()
  assert.equal(deck.snapshot().lost, true)
  assert.equal(deck.snapshot().conflicts, 1)
  await deck.act(point("a"))
  assert.equal(server.events.length, 1)
})

test("the server holding another event at that place is a conflict: kept, shown, nothing overwritten", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const deck = tab(device, server, "tab-1")
  await deck.open()
  await deck.act(START)
  await deck.flush()
  server.online = false
  await deck.act({ type: "timeout", side: "a" })
  await deck.act(point("a"))
  // Scored from somewhere else meanwhile, under the same assignment.
  server.events.push({ id: "theirs", sequence: 2, event: point("b") })
  server.online = true
  await deck.flush()
  const view = deck.snapshot()
  assert.equal(view.pending, 0)
  assert.equal(view.conflicts, 2)
  assert.deepEqual(view.state?.points, [0, 1])
  assert.deepEqual(server.events.map((kept) => kept.id).slice(1), ["theirs"])
})

test("an event the server's rules refuse is set aside with what followed it, and the deck shows the server's score", async () => {
  const device = new IDBFactory()
  const server = new Server()
  server.noTimeouts = true
  const deck = tab(device, server, "tab-1")
  await deck.open()
  await deck.act(START)
  await deck.act(point("a"))
  await deck.act({ type: "timeout", side: "a" })
  await deck.act(point("a"))
  await deck.flush()
  const view = deck.snapshot()
  assert.equal(view.problem, "refused:timeout_used")
  assert.deepEqual(view.state?.points, [1, 0], "the point before the refusal stands, the one after it doesn't")
  assert.deepEqual(view.state?.timeouts, [false, false])
  assert.equal(view.pending, 0)
  assert.equal(view.conflicts, 2, "what was shown as scored and then refused is not thrown away")
  assert.equal(server.events.length, 2)
  // The stream goes on from the server's revision.
  await deck.act(point("b"))
  await deck.flush()
  assert.deepEqual(server.state().points, [1, 1])
  assert.equal(server.events.at(-1)?.sequence, 3)
})

test("a tap made while the server is being asked is neither lost nor turned into a conflict", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const deck = tab(device, server, "tab-1")
  await deck.open()
  await deck.act(START)
  await deck.flush()

  let release = () => {}
  server.gate = new Promise((resolve) => (release = resolve))
  const reread = deck.load() // coming back to the tab: the server is asked, and takes its time
  const tapped = deck.act(point("a")) // the umpire taps meanwhile
  await tapped
  assert.deepEqual(deck.snapshot().state?.points, [1, 0])
  release()
  server.gate = null
  await reread
  await deck.flush()
  const view = deck.snapshot()
  assert.deepEqual(view.state?.points, [1, 0], "still on screen after the reread")
  assert.equal(view.conflicts, 0)
  await deck.act(point("a"))
  await deck.flush()
  assert.deepEqual(server.state().points, [2, 0])
  assert.equal(deck.snapshot().sync, "saved")
})

test("a whole match finished offline is restored after a restart and accepted as finished", async () => {
  const device = new IDBFactory()
  const server = new Server()
  let deck = tab(device, server, "tab-1")
  await deck.open()
  server.online = false
  await deck.act(START)
  for (let n = 0; n < 22; n++) await deck.act(point("a")) // 11-0, 11-0
  assert.equal(deck.snapshot().state?.status, "completed")
  await deck.act(point("b"))
  assert.equal(deck.snapshot().problem, "not_in_progress")
  await deck.close()

  deck = tab(device, server, "tab-2")
  await deck.open()
  assert.equal(deck.snapshot().state?.status, "completed")
  assert.equal(deck.snapshot().pending, 23)
  server.online = true
  await deck.load()
  await deck.flush()
  assert.equal(server.state().status, "completed")
  assert.deepEqual(server.state().games, [[11, 0], [11, 0]])
  assert.equal(deck.snapshot().card?.revision, 23, "the revision a confirmation is made against")
})

test("a reload is the same tab and keeps its sheet; a new tab has to wait", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const before = tab(device, server, "tab-1")
  await before.open()
  await before.act(START)
  // The page is reloaded without a chance to release its claim.
  const reloaded = tab(device, server, "tab-1")
  await reloaded.open()
  assert.equal(reloaded.snapshot().readOnly, false)
  const another = tab(device, server, "tab-2")
  await another.open()
  assert.equal(another.snapshot().readOnly, true)
})

test("a write the browser aborts is reported as a storage failure and leaves nothing behind", async () => {
  const device = new IDBFactory()
  const journal = await Journal.open(device)
  await journal.claim("sheet", "tab-1")
  const sheet = { scorecardId: "sheet", userId: "umpire", assignmentId: "assignment-1", revision: 0 }
  // A value IndexedDB can't store makes the put fail and the transaction abort, like a full disk does.
  const unstorable = { type: "point", side: () => "a" }
  await assert.rejects(
    journal.append(sheet, "tab-1", () => ({ id: "x", event: unstorable, device_time: "" })),
    (error: unknown) => error instanceof JournalError && error.code === "storage"
  )
  assert.deepEqual((await journal.read("sheet", "umpire")).events, [])
  // The journal still works afterwards, and the sequence wasn't used up.
  const written = await journal.append(sheet, "tab-1", () => ({ id: "y", event: point("a"), device_time: "" }))
  assert.equal(written.sequence, 1)
  await assert.rejects(
    journal.append(sheet, "tab-2", () => ({ id: "z", event: point("a"), device_time: "" })),
    (error: unknown) => error instanceof JournalError && error.code === "not_owner"
  )
})

test("two accounts on one device never touch each other's records, and logging out counts what isn't on the server", async () => {
  const device = new IDBFactory()
  const server = new Server()
  const first = tab(device, server, "tab-1")
  await first.open()
  server.online = false
  await first.act(START)
  await first.act(point("a"))
  await first.close() // the first umpire's session ends with two actions unsent

  const journal = await Journal.open(device)
  assert.equal(await journal.unsent("umpire"), 2)
  assert.equal(await journal.unsent("somebody-else"), 0)
  const theirs = await journal.read("sheet", "somebody-else")
  assert.equal(theirs.sheet, null)
  assert.deepEqual(theirs.events, [])

  // Offline, the second account has nothing on this device to open.
  const second = tab(device, server, "tab-2", { userId: "somebody-else" })
  await second.open()
  assert.ok(second.snapshot().failure)
  // Online, the second account scores the same sheet from the start; the first one's leftovers
  // neither shift its sequence numbers nor get deleted by it.
  server.online = true
  await second.load()
  await second.act(START)
  await second.act(point("b"))
  await second.flush()
  assert.deepEqual(server.events.map((kept) => kept.sequence), [1, 2])
  assert.equal(second.snapshot().sync, "saved")
  assert.equal(await journal.unsent("umpire"), 2, "still there for the first account")
  assert.equal(await journal.unsent("somebody-else"), 0)

  await second.close()
  // The first account comes back: its two actions can't follow the stream any more, so they are kept
  // as conflicts, and those still count as not being on the server when it logs out.
  const back = tab(device, server, "tab-3")
  await back.open()
  await back.flush()
  assert.equal(back.snapshot().conflicts, 2)
  assert.equal(await journal.unsent("umpire"), 2)
  await journal.purge("umpire")
  assert.equal(await journal.unsent("umpire"), 0)
  assert.equal((await journal.read("sheet", "umpire")).sheet, null)
  assert.equal((await journal.read("sheet", "somebody-else")).sheet === null, false, "the other account's copy is untouched")
})
