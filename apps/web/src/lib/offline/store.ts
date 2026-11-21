// Changes made without a connection, and the data screens last showed (REQ-035). Kept in IndexedDB
// so they survive a closed tab or a restart.
//
// A change is written here first. It is sent with its id as the Idempotency-Key header, so if a reply
// is lost and the change is sent again, the server answers from its record and doesn't make it twice
// (core.middleware.IdempotencyMiddleware). Changes go in the order they were made. A change the server
// refuses is set aside with the server's message, never dropped quietly. The person retries it (under a
// new key, because the server keeps its refusal under the old one) or discards it.
//
// Everything is scoped to the account that made it: another account on the same device never sends or
// sees it. Score actions have their own journal (lib/deck/journal.ts).
//
// This file has no imports from the app, so it runs under Node with a stand-in IndexedDB in tests.

export const DB_NAME = "coast-tt-offline"
const VERSION = 1

export interface PendingChange {
  /** Also the Idempotency-Key it is sent with. */
  id: string
  userId: string
  method: "POST" | "PATCH" | "PUT" | "DELETE"
  path: string
  body: unknown
  /** What the change does, in words, for the list of changes waiting. */
  label: string
  /** Query keys to refresh once it is through. */
  refresh: unknown[][]
  createdAt: string
  state: "waiting" | "refused"
  /** Why the server refused it, in its words. */
  message?: string
  code?: string
}

/** The saved screens of one account: a dehydrated query cache. */
export interface SavedCache {
  userId: string
  savedAt: string
  build: string
  state: unknown
}

/** What happened to one change on its way to the server. */
export type Outcome =
  | { kind: "sent" }
  /** No connection, or the server is busy or down: keep it and the ones after it for later. */
  | { kind: "later" }
  /** The server won't take it: set it aside with the server's message and go on with the next. */
  | { kind: "refused"; message: string; code?: string }
  /** The session has ended or the app is out of date: nothing more can be sent until that is fixed. */
  | { kind: "stop"; reason: "signed_out" | "outdated" }

export type Send = (change: PendingChange) => Promise<Outcome>

export type FlushResult = { sent: PendingChange[]; refused: number; stopped?: "signed_out" | "outdated"; offline: boolean }

export class StorageError extends Error {
  constructor(cause?: unknown) {
    const name = cause && typeof cause === "object" && "name" in cause ? String((cause as { name: unknown }).name) : ""
    super(name === "QuotaExceededError" ? "This device's storage is full." : "This device couldn't save the change.")
  }
}

const done = <T>(request: IDBRequest<T>) =>
  new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })

const committed = (tx: IDBTransaction) =>
  new Promise<void>((resolve, reject) => {
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error ?? new Error("aborted"))
  })

export function upgrade(db: IDBDatabase) {
  if (!db.objectStoreNames.contains("changes")) {
    const changes = db.createObjectStore("changes", { keyPath: "id" })
    changes.createIndex("byUser", "userId")
  }
  if (!db.objectStoreNames.contains("screens")) db.createObjectStore("screens", { keyPath: "userId" })
}

export class OfflineStore {
  private db: Promise<IDBDatabase> | null = null
  private readonly factory: IDBFactory

  constructor(factory: IDBFactory) {
    this.factory = factory
  }

  private open(): Promise<IDBDatabase> {
    this.db ??= new Promise<IDBDatabase>((resolve, reject) => {
      const request = this.factory.open(DB_NAME, VERSION)
      request.onupgradeneeded = () => upgrade(request.result)
      request.onsuccess = () => {
        const db = request.result
        // A newer version in another tab asks for the database: let it go and open again next time.
        db.onversionchange = () => {
          db.close()
          this.db = null
        }
        resolve(db)
      }
      request.onerror = () => reject(request.error)
      request.onblocked = () => reject(new Error("blocked"))
    }).catch((error) => {
      this.db = null
      throw error
    })
    return this.db
  }

  private async write(stores: string[], work: (tx: IDBTransaction) => void): Promise<void> {
    try {
      const tx = (await this.open()).transaction(stores, "readwrite")
      work(tx)
      await committed(tx)
    } catch (error) {
      throw new StorageError(error)
    }
  }

  /** Keep a change. Resolves only once it is on the device: until then it isn't saved. */
  add(change: PendingChange): Promise<void> {
    return this.write(["changes"], (tx) => void tx.objectStore("changes").add(change))
  }

  /** The account's changes, oldest first. */
  async list(userId: string): Promise<PendingChange[]> {
    const tx = (await this.open()).transaction("changes", "readonly")
    const all = await done(tx.objectStore("changes").index("byUser").getAll(userId) as IDBRequest<PendingChange[]>)
    return all.sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id))
  }

  /** Every account's changes still on the device, for logging out and updating safely. */
  async countAll(): Promise<number> {
    const tx = (await this.open()).transaction("changes", "readonly")
    return done(tx.objectStore("changes").count())
  }

  remove(id: string): Promise<void> {
    return this.write(["changes"], (tx) => void tx.objectStore("changes").delete(id))
  }

  private refuse(change: PendingChange, message: string, code?: string): Promise<void> {
    return this.write(["changes"], (tx) => void tx.objectStore("changes").put({ ...change, state: "refused", message, code }))
  }

  /** Send a refused change again, under a new key: the server keeps its refusal under the old one. */
  async retry(id: string, newId: string): Promise<void> {
    const tx0 = (await this.open()).transaction("changes", "readonly")
    const change = await done(tx0.objectStore("changes").get(id) as IDBRequest<PendingChange | undefined>)
    if (!change) return
    const again: PendingChange = { ...change, id: newId, state: "waiting", message: undefined, code: undefined }
    await this.write(["changes"], (tx) => {
      tx.objectStore("changes").delete(id)
      tx.objectStore("changes").add(again)
    })
  }

  /**
   * Send the account's waiting changes in order, one at a time. A change goes only after the one before
   * it got an answer. With no connection the rest wait, in order, for the next try.
   */
  async flush(userId: string, send: Send): Promise<FlushResult> {
    const result: FlushResult = { sent: [], refused: 0, offline: false }
    for (const change of await this.list(userId)) {
      if (change.state !== "waiting") continue
      const outcome = await send(change)
      if (outcome.kind === "sent") {
        await this.remove(change.id)
        result.sent.push(change)
      } else if (outcome.kind === "refused") {
        await this.refuse(change, outcome.message, outcome.code)
        result.refused += 1
      } else if (outcome.kind === "later") {
        result.offline = true
        break
      } else {
        result.stopped = outcome.reason
        break
      }
    }
    return result
  }

  /** Forget an account's changes, after it has sent or discarded them (logging out). */
  async purge(userId: string): Promise<void> {
    const ids = (await this.list(userId)).map((change) => change.id)
    await this.write(["changes", "screens"], (tx) => {
      for (const id of ids) tx.objectStore("changes").delete(id)
      tx.objectStore("screens").delete(userId)
    })
  }

  async saveScreens(saved: SavedCache): Promise<void> {
    await this.write(["screens"], (tx) => void tx.objectStore("screens").put(saved))
  }

  async loadScreens(userId: string): Promise<SavedCache | undefined> {
    const tx = (await this.open()).transaction("screens", "readonly")
    return done(tx.objectStore("screens").get(userId) as IDBRequest<SavedCache | undefined>)
  }

  /** Keep only this account's saved screens: on a shared device the last person's stay private. */
  async keepScreensOf(userId: string): Promise<void> {
    const tx0 = (await this.open()).transaction("screens", "readonly")
    const users = (await done(tx0.objectStore("screens").getAllKeys())) as string[]
    const others = users.filter((user) => user !== userId)
    if (others.length === 0) return
    await this.write(["screens"], (tx) => {
      for (const user of others) tx.objectStore("screens").delete(user)
    })
  }
}
