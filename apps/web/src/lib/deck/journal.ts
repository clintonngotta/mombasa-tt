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
// Version 2 keys sheets and events by account. Version 1 was only ever in development builds.
const VERSION = 2
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
  /** The server revision the device had seen when it wrote the event. */
  expectedRevision: number
  userId: string
  /** Not accepted by the server and not to be sent again: kept so that it stays visible. */
  conflict?: boolean
  /** A conflict's place in the stream when it was written (its key is moved out of the stream). */
  wasSequence?: number
  /** A conflict the organizers have been sent. */
  reported?: boolean
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

/**
 * Bring the database from `from` up to VERSION, inside the upgrade transaction (REQ-035): a step fails
 * as a whole and leaves the old version in place. A release changes the layout only by adding a step
 * here that carries every kept sheet and event across; it never deletes a store that may hold unsent
 * actions.
 */
export function upgrade(db: IDBDatabase, from: number) {
  if (from < 2) {
    // Version 1 was only ever in development builds and its keys can't be read: start clean.
    for (const name of Array.from(db.objectStoreNames)) db.deleteObjectStore(name)
    // Sheets and events are keyed by account first: two accounts on one device never share a record.
    db.createObjectStore("sheets", { keyPath: ["userId", "scorecardId"] })
    db.createObjectStore("owners", { keyPath: "scorecardId" })
    db.createObjectStore("events", { keyPath: ["userId", "scorecardId", "sequence"] })
  }
}

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
      request.onupgradeneeded = (change) => {
        upgrade(request.result, change.oldVersion)
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
        // A score write must be on disk when the transaction completes, not merely handed to the OS.
        tx = this.db.transaction(stores, mode, mode === "readwrite" ? { durability: "strict" } : undefined)
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

  /** The standing events of one account's sheet, in order (conflicts are kept under negative numbers). */
  private static eventsOf(tx: IDBTransaction, userId: string, scorecardId: string) {
    const range = IDBKeyRange.bound([userId, scorecardId, 0], [userId, scorecardId, Number.MAX_SAFE_INTEGER])
    return done(tx.objectStore("events").getAll(range)) as Promise<JournalEvent[]>
  }

  private static conflictRange(userId: string, scorecardId: string) {
    return IDBKeyRange.bound([userId, scorecardId, -Number.MAX_SAFE_INTEGER], [userId, scorecardId, -1])
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
      const standing = await Journal.eventsOf(tx, sheet.userId, sheet.scorecardId)
      const last = standing.length ? standing[standing.length - 1].sequence : sheet.revision
      const sequence = Math.max(last, sheet.revision) + 1
      const written: JournalEvent<E> = {
        scorecardId: sheet.scorecardId,
        sequence,
        userId: sheet.userId,
        assignmentId: sheet.assignmentId,
        expectedRevision: sheet.revision,
        ...make(sequence),
      }
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
      for (const kept of await Journal.eventsOf(tx, sheet.userId, sheet.scorecardId)) {
        if (kept.sequence <= sheet.revision) await done(events.delete([kept.userId, kept.scorecardId, kept.sequence]))
      }
    })
  }

  /** The server holds the stream up to `revision`: those events no longer count as unsent. */
  markAcked(scorecardId: string, userId: string, revision: number): Promise<void> {
    return this.run(["sheets"], "readwrite", async (tx) => {
      const sheets = tx.objectStore("sheets")
      const sheet = (await done(sheets.get([userId, scorecardId]))) as JournalSheet | undefined
      if (sheet && revision > sheet.acked) await done(sheets.put({ ...sheet, acked: revision }))
    })
  }

  /** The sheet as last kept for this account, with every journal event of it in order. */
  read<C, E>(scorecardId: string, userId: string): Promise<{ sheet: JournalSheet<C> | null; events: JournalEvent<E>[] }> {
    return this.run(["sheets", "events"], "readonly", async (tx) => {
      const sheet = (await done(tx.objectStore("sheets").get([userId, scorecardId]))) as JournalSheet<C> | undefined
      const events = (await Journal.eventsOf(tx, userId, scorecardId)) as JournalEvent<E>[]
      return { sheet: sheet ?? null, events }
    })
  }

  /**
   * Events from `fromSequence` on were not accepted by the server. They are never sent again, and they
   * are never thrown away either: they stay on the device as conflicts, out of the stream's sequence
   * numbers, until the umpire has seen them. Returns how many were set aside.
   */
  setAside(scorecardId: string, userId: string, fromSequence: number): Promise<number> {
    return this.run(["events"], "readwrite", async (tx) => {
      const events = tx.objectStore("events")
      const already = (await done(events.getAll(Journal.conflictRange(userId, scorecardId)))) as JournalEvent[]
      let place = already.length ? Math.min(...already.map((kept) => kept.sequence)) : 0
      let count = 0
      for (const kept of await Journal.eventsOf(tx, userId, scorecardId)) {
        if (kept.sequence < fromSequence) continue
        count += 1
        place -= 1
        await done(events.delete([kept.userId, kept.scorecardId, kept.sequence]))
        await done(events.put({ ...kept, sequence: place, conflict: true, wasSequence: kept.sequence } as JournalEvent))
      }
      return count
    })
  }

  /** Conflicts of a sheet: actions scored on this device that the server didn't accept. */
  conflicts<E>(scorecardId: string, userId: string): Promise<JournalEvent<E>[]> {
    return this.run(["events"], "readonly", async (tx) => (await done(tx.objectStore("events").getAll(Journal.conflictRange(userId, scorecardId)))) as JournalEvent<E>[])
  }

  /** The organizers have these conflicts now. */
  markReported(scorecardId: string, userId: string, ids: string[]): Promise<void> {
    return this.run(["events"], "readwrite", async (tx) => {
      const events = tx.objectStore("events")
      for (const kept of (await done(events.getAll(Journal.conflictRange(userId, scorecardId)))) as JournalEvent[]) {
        if (ids.includes(kept.id) && !kept.reported) await done(events.put({ ...kept, reported: true }))
      }
    })
  }

  /** The umpire has dealt with the conflicts of a sheet: remove them from the device. */
  clearConflicts(scorecardId: string, userId: string): Promise<void> {
    return this.run(["events"], "readwrite", async (tx) => {
      await done(tx.objectStore("events").delete(Journal.conflictRange(userId, scorecardId)))
    })
  }

  private static ofUser(userId: string) {
    return IDBKeyRange.bound([userId], [userId, []])
  }

  /**
   * How many of the account's actions are on this device and not on the server: those still to be
   * sent, and conflicts nobody has dealt with yet.
   */
  unsent(userId: string): Promise<number> {
    return this.run(["sheets", "events"], "readonly", async (tx) => {
      const events = (await done(tx.objectStore("events").getAll(Journal.ofUser(userId)))) as JournalEvent[]
      const sheets = (await done(tx.objectStore("sheets").getAll(Journal.ofUser(userId)))) as JournalSheet[]
      const acked = new Map(sheets.map((sheet) => [sheet.scorecardId, sheet.acked]))
      return events.filter((kept) => kept.conflict || kept.sequence > (acked.get(kept.scorecardId) ?? 0)).length
    })
  }

  /**
   * How many actions of any account on this device are not on the server. A new version of the app
   * waits while this is above zero (REQ-035), whoever is signed in now.
   */
  unsentOnDevice(): Promise<number> {
    return this.run(["sheets", "events"], "readonly", async (tx) => {
      const events = (await done(tx.objectStore("events").getAll())) as JournalEvent[]
      const sheets = (await done(tx.objectStore("sheets").getAll())) as JournalSheet[]
      const acked = new Map(sheets.map((sheet) => [`${sheet.userId}\n${sheet.scorecardId}`, sheet.acked]))
      return events.filter((kept) => kept.conflict || kept.sequence > (acked.get(`${kept.userId}\n${kept.scorecardId}`) ?? 0)).length
    })
  }

  /** How many sheets a tab on this device is scoring now: it has renewed its claim lately. */
  scoringNow(now = Date.now()): Promise<number> {
    return this.run(["owners"], "readonly", async (tx) => {
      const owners = (await done(tx.objectStore("owners").getAll())) as Owner[]
      return owners.filter((owner) => now - owner.beat < OWNER_STALE_MS).length
    })
  }

  /** Remove everything kept for an account (after logout, once nothing of it is unsent). */
  purge(userId: string): Promise<void> {
    return this.run(["sheets", "events"], "readwrite", async (tx) => {
      await done(tx.objectStore("events").delete(Journal.ofUser(userId)))
      await done(tx.objectStore("sheets").delete(Journal.ofUser(userId)))
    })
  }
}
