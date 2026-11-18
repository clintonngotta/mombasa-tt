// The score journal (REQ-013): every action the umpire takes is written to IndexedDB before the deck
// shows it, so a point the umpire has seen acknowledged survives a closed tab, a restart or a lost
// connection, and is sent once the server can be reached.
//
// Records are scoped to the account and the sheet. One tab at a time owns a sheet: the owner check and
// the allocation of the next sequence number happen in the same transaction as the write, so two tabs
// can never both write an event at one place in the stream.
//
// This file has no imports from the app, so it runs under Node with a stand-in IndexedDB in tests.

export const DB_NAME = "coast-tt-scoring"
const VERSION = 1
/** A tab that hasn't renewed its claim for this long has gone (closed, crashed, discarded). */
export const OWNER_STALE_MS = 10_000

/** One action as it is kept on the device. `event` is the scoring engine's event, untouched. */
export interface JournalEvent<E = unknown> {
  scorecardId: string
  sequence: number
  /** The event's own id, sent to the server so a retry is recognised. */
  id: string
  event: E
  device_time: string
  /** The assignment the device held when it wrote the event. */
  assignmentId: string
  userId: string
  /** Not accepted by the server and not to be sent again: kept so that it stays visible. */
  conflict?: boolean
}

/** The sheet as last downloaded, so the deck can open without the server. */
export interface JournalSheet<C = unknown> {
  scorecardId: string
  userId: string
  card: C
  /** The server revision of `card`: journal events up to it are part of the card already. */
  revision: number
  /** The highest sequence the server is known to hold: journal events after it are still to be sent. */
  acked: number
  savedAt: string
}

interface Owner {
  scorecardId: string
  tabId: string
  beat: number
}

export class JournalError extends Error {
  /** "not_owner": another tab owns the sheet. "storage": the device couldn't write. */
  readonly code: "not_owner" | "storage"

  constructor(code: "not_owner" | "storage", cause?: unknown) {
    super(code === "storage" ? `The device couldn't save: ${describeCause(cause)}` : "Another tab is scoring this match.")
    this.code = code
  }
}

function describeCause(cause: unknown): string {
  if (cause && typeof cause === "object" && "name" in cause) {
    const name = String((cause as { name: unknown }).name)
    return name === "QuotaExceededError" ? "its storage is full" : name
  }
  return "storage is unavailable"
}

const done = <T>(request: IDBRequest<T>) =>
  new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })

export class Journal {
  private readonly db: IDBDatabase

  private constructor(db: IDBDatabase) {
    this.db = db
  }

  /** Open (and create) the journal. Rejects with JournalError("storage") where IndexedDB can't be used. */
  static open(factory: IDBFactory | undefined = globalThis.indexedDB, name = DB_NAME): Promise<Journal> {
    return new Promise((resolve, reject) => {
      if (!factory) return reject(new JournalError("storage"))
      let request: IDBOpenDBRequest
      try {
        request = factory.open(name, VERSION)
      } catch (error) {
        return reject(new JournalError("storage", error))
      }
      request.onupgradeneeded = () => {
        const db = request.result
        db.createObjectStore("sheets", { keyPath: "scorecardId" })
        db.createObjectStore("owners", { keyPath: "scorecardId" })
        const events = db.createObjectStore("events", { keyPath: ["scorecardId", "sequence"] })
        events.createIndex("by_user", "userId")
      }
      request.onsuccess = () => resolve(new Journal(request.result))
      request.onerror = () => reject(new JournalError("storage", request.error))
      request.onblocked = () => reject(new JournalError("storage"))
    })
  }

  close() {
    this.db.close()
  }

  /**
   * Run `work` in one transaction and resolve with its result once the transaction has committed:
   * only then is anything in it durable. A failed or aborted transaction (quota, a full disk, a
   * private window) rejects with JournalError("storage") and nothing in it was written.
   */
  private run<T>(stores: string[], mode: IDBTransactionMode, work: (tx: IDBTransaction) => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      let tx: IDBTransaction
      try {
        tx = this.db.transaction(stores, mode)
      } catch (error) {
        return reject(new JournalError("storage", error))
      }
      let result: T
      let failure: unknown
      tx.oncomplete = () => resolve(result)
      tx.onabort = () => reject(failure instanceof JournalError ? failure : new JournalError("storage", failure ?? tx.error))
      tx.onerror = () => {
        failure ??= tx.error
      }
      work(tx).then(
        (value) => {
          result = value
        },
        (error: unknown) => {
          failure = error
          try {
            tx.abort()
          } catch {
            // already finished or aborted
          }
        }
      )
    })
  }

  private static eventsOf(tx: IDBTransaction, scorecardId: string) {
    const range = IDBKeyRange.bound([scorecardId, 0], [scorecardId, Number.MAX_SAFE_INTEGER])
    return done(tx.objectStore("events").getAll(range)) as Promise<JournalEvent[]>
  }

  /**
   * Take the sheet for this tab. True if it is ours: nobody held it, we already did, or the tab that
   * did has stopped renewing its claim.
   */
  claim(scorecardId: string, tabId: string, now = Date.now()): Promise<boolean> {
    return this.run(["owners"], "readwrite", async (tx) => {
      const owners = tx.objectStore("owners")
      const owner = (await done(owners.get(scorecardId))) as Owner | undefined
      if (owner && owner.tabId !== tabId && now - owner.beat < OWNER_STALE_MS) return false
      await done(owners.put({ scorecardId, tabId, beat: now } satisfies Owner))
      return true
    })
  }

  /** Give the sheet up, if it is still ours. */
  release(scorecardId: string, tabId: string): Promise<void> {
    return this.run(["owners"], "readwrite", async (tx) => {
      const owners = tx.objectStore("owners")
      const owner = (await done(owners.get(scorecardId))) as Owner | undefined
      if (owner?.tabId === tabId) await done(owners.delete(scorecardId))
    })
  }

  /**
   * Write one action. In a single transaction: check this tab still owns the sheet, take the next
   * sequence number, write the event. Resolves only once that is committed; until then the deck must
   * not show the action.
   */
  append<E>(sheet: { scorecardId: string; userId: string; assignmentId: string; revision: number }, tabId: string, make: (sequence: number) => { id: string; event: E; device_time: string }, now = Date.now()): Promise<JournalEvent<E>> {
    return this.run(["owners", "events"], "readwrite", async (tx) => {
      const owners = tx.objectStore("owners")
      const owner = (await done(owners.get(sheet.scorecardId))) as Owner | undefined
      if (owner?.tabId !== tabId) throw new JournalError("not_owner")
      const standing = (await Journal.eventsOf(tx, sheet.scorecardId)).filter((kept) => !kept.conflict)
      const last = standing.length ? standing[standing.length - 1].sequence : sheet.revision
      const sequence = Math.max(last, sheet.revision) + 1
      const written: JournalEvent<E> = { scorecardId: sheet.scorecardId, sequence, userId: sheet.userId, assignmentId: sheet.assignmentId, ...make(sequence) }
      await done(tx.objectStore("events").put(written))
      await done(owners.put({ scorecardId: sheet.scorecardId, tabId, beat: now } satisfies Owner))
      return written
    })
  }

  /**
   * Keep the sheet as the server just gave it, and drop the journal events it already contains
   * (sequence up to its revision). Events after it stay: they are still to be sent.
   */
  saveSheet<C>(sheet: Omit<JournalSheet<C>, "savedAt" | "acked">): Promise<void> {
    return this.run(["sheets", "events"], "readwrite", async (tx) => {
      await done(tx.objectStore("sheets").put({ ...sheet, acked: sheet.revision, savedAt: new Date().toISOString() } satisfies JournalSheet<C>))
      const events = tx.objectStore("events")
      for (const kept of await Journal.eventsOf(tx, sheet.scorecardId)) {
        if (kept.sequence <= sheet.revision && !kept.conflict) await done(events.delete([kept.scorecardId, kept.sequence]))
      }
    })
  }

  /** The server holds the stream up to `revision`: those events no longer count as unsent. */
  markAcked(scorecardId: string, revision: number): Promise<void> {
    return this.run(["sheets"], "readwrite", async (tx) => {
      const sheets = tx.objectStore("sheets")
      const sheet = (await done(sheets.get(scorecardId))) as JournalSheet | undefined
      if (sheet && revision > sheet.acked) await done(sheets.put({ ...sheet, acked: revision }))
    })
  }

  /** The sheet as last kept for this account, with every journal event of it in order. */
  read<C, E>(scorecardId: string, userId: string): Promise<{ sheet: JournalSheet<C> | null; events: JournalEvent<E>[] }> {
    return this.run(["sheets", "events"], "readonly", async (tx) => {
      const sheet = (await done(tx.objectStore("sheets").get(scorecardId))) as JournalSheet<C> | undefined
      const events = (await Journal.eventsOf(tx, scorecardId)) as JournalEvent<E>[]
      return { sheet: sheet && sheet.userId === userId ? sheet : null, events: events.filter((kept) => kept.userId === userId) }
    })
  }

  /**
   * Events from `fromSequence` on were not accepted. `keep` marks them as conflicts, which stay on the
   * device and visible but are never sent again; otherwise they are removed (the rules refused them).
   */
  setAside(scorecardId: string, fromSequence: number, keep: boolean): Promise<number> {
    return this.run(["events"], "readwrite", async (tx) => {
      const events = tx.objectStore("events")
      let count = 0
      for (const kept of await Journal.eventsOf(tx, scorecardId)) {
        if (kept.sequence < fromSequence || kept.conflict) continue
        count += 1
        await done(events.delete([kept.scorecardId, kept.sequence]))
        // A conflict moves out of the stream's sequence numbers, so the stream can go on from there.
        if (keep) await done(events.put({ ...kept, sequence: -Date.now() - count, conflict: true, wasSequence: kept.sequence } as JournalEvent))
      }
      return count
    })
  }

  /** Conflicts of a sheet: actions scored on this device that the server didn't accept. */
  async conflicts<E>(scorecardId: string, userId: string): Promise<JournalEvent<E>[]> {
    return this.run(["events"], "readonly", async (tx) => {
      const range = IDBKeyRange.bound([scorecardId, -Number.MAX_SAFE_INTEGER], [scorecardId, -1])
      const kept = (await done(tx.objectStore("events").getAll(range))) as JournalEvent<E>[]
      return kept.filter((event) => event.userId === userId)
    })
  }

  /** The umpire has dealt with the conflicts of a sheet: remove them from the device. */
  clearConflicts(scorecardId: string): Promise<void> {
    return this.run(["events"], "readwrite", async (tx) => {
      const range = IDBKeyRange.bound([scorecardId, -Number.MAX_SAFE_INTEGER], [scorecardId, -1])
      await done(tx.objectStore("events").delete(range))
    })
  }

  /** How many of the account's actions are on this device and not yet known to be on the server. */
  unsent(userId: string): Promise<number> {
    return this.run(["sheets", "events"], "readonly", async (tx) => {
      const events = (await done(tx.objectStore("events").index("by_user").getAll(userId))) as JournalEvent[]
      const sheets = (await done(tx.objectStore("sheets").getAll())) as JournalSheet[]
      const revision = new Map(sheets.map((sheet) => [sheet.scorecardId, sheet.acked]))
      return events.filter((kept) => !kept.conflict && kept.sequence > (revision.get(kept.scorecardId) ?? 0)).length
    })
  }

  /** Remove everything kept for an account (after logout, once nothing of it is unsent). */
  purge(userId: string): Promise<void> {
    return this.run(["sheets", "events"], "readwrite", async (tx) => {
      const events = tx.objectStore("events")
      for (const kept of (await done(events.index("by_user").getAll(userId))) as JournalEvent[]) {
        await done(events.delete([kept.scorecardId, kept.sequence]))
      }
      const sheets = tx.objectStore("sheets")
      for (const sheet of (await done(sheets.getAll())) as JournalSheet[]) {
        if (sheet.userId === userId) await done(sheets.delete(sheet.scorecardId))
      }
    })
  }
}
