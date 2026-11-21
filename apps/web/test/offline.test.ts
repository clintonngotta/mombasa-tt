// Changes kept offline and sent later (REQ-035), run under Node with a stand-in IndexedDB:
//   node --experimental-strip-types --test test/offline.test.ts
// "The server" models the API's Idempotency-Key handling: a key it has seen gets the kept answer.
import assert from "node:assert/strict"
import { test } from "node:test"
import { IDBFactory } from "fake-indexeddb"
import { OfflineStore, StorageError, type Outcome, type PendingChange } from "../src/lib/offline/store.ts"

let clock = 0
function change(userId: string, label: string, path = "/things/"): PendingChange {
  clock += 1
  return {
    id: `key-${label}-${clock}`,
    userId,
    method: "POST",
    path,
    body: { label },
    label,
    refresh: [["things"]],
    createdAt: new Date(Date.UTC(2026, 10, 21, 10, 0, clock)).toISOString(),
    state: "waiting",
  }
}

class Server {
  online = true
  loseReply = false
  signedIn = true
  /** Paths the server refuses, with its message. */
  refuses = new Map<string, string>()
  made: string[] = []
  answered = new Map<string, Outcome>()

  send = async (c: PendingChange): Promise<Outcome> => {
    if (!this.online) return { kind: "later" }
    if (!this.signedIn) return { kind: "stop", reason: "signed_out" }
    const kept = this.answered.get(c.id)
    if (kept) return kept // a repeat: the first answer, nothing made twice
    const refusal = this.refuses.get(c.path)
    const outcome: Outcome = refusal ? { kind: "refused", message: refusal, code: "conflict" } : { kind: "sent" }
    if (!refusal) this.made.push(c.label)
    this.answered.set(c.id, outcome)
    if (this.loseReply) {
      this.loseReply = false
      return { kind: "later" } // got through, but the device never heard
    }
    return outcome
  }
}

test("changes made offline are sent once, in order, when the connection is back", async () => {
  const store = new OfflineStore(new IDBFactory())
  const server = new Server()
  server.online = false
  for (const label of ["first", "second", "third"]) await store.add(change("ama", label))
  const offline = await store.flush("ama", server.send)
  assert.equal(offline.offline, true)
  assert.equal((await store.list("ama")).length, 3)

  server.online = true
  server.loseReply = true
  const lost = await store.flush("ama", server.send)
  assert.deepEqual(lost.sent.map((c) => c.label), [])
  assert.deepEqual(server.made, ["first"]) // made, but the device didn't hear: kept for the retry
  const back = await store.flush("ama", server.send)
  assert.deepEqual(back.sent.map((c) => c.label), ["first", "second", "third"])
  assert.deepEqual(server.made, ["first", "second", "third"]) // "first" not made twice
  assert.deepEqual(await store.list("ama"), [])
})

test("a refused change is set aside with the server's reason, and the rest still go", async () => {
  const store = new OfflineStore(new IDBFactory())
  const server = new Server()
  server.refuses.set("/closed/", "The meeting has ended.")
  await store.add(change("ama", "a"))
  await store.add(change("ama", "late", "/closed/"))
  await store.add(change("ama", "b"))
  const result = await store.flush("ama", server.send)
  assert.equal(result.refused, 1)
  assert.deepEqual(server.made, ["a", "b"])
  const [kept] = await store.list("ama")
  assert.equal(kept.state, "refused")
  assert.equal(kept.message, "The meeting has ended.")
  // Not sent again by itself.
  await store.flush("ama", server.send)
  assert.equal((await store.list("ama"))[0].state, "refused")

  // Tried again under a new key once the person decides; the server takes it this time.
  server.refuses.clear()
  await store.retry(kept.id, "key-again")
  const again = await store.flush("ama", server.send)
  assert.deepEqual(again.sent.map((c) => c.id), ["key-again"])
  assert.deepEqual(server.made, ["a", "b", "late"])
})

test("a refused retry under the old key would replay the refusal: retry uses a new key", async () => {
  const store = new OfflineStore(new IDBFactory())
  const server = new Server()
  server.refuses.set("/x/", "No.")
  const c = change("ama", "x", "/x/")
  await store.add(c)
  await store.flush("ama", server.send)
  server.refuses.clear()
  assert.deepEqual(await server.send(c), { kind: "refused", message: "No.", code: "conflict" })
  await store.retry(c.id, "fresh-key")
  assert.deepEqual((await store.list("ama")).map((k) => [k.id, k.state, k.createdAt]), [["fresh-key", "waiting", c.createdAt]])
})

test("a session that ended stops sending; nothing is lost until the same person logs in", async () => {
  const store = new OfflineStore(new IDBFactory())
  const server = new Server()
  server.signedIn = false
  await store.add(change("ama", "a"))
  await store.add(change("ama", "b"))
  const stopped = await store.flush("ama", server.send)
  assert.equal(stopped.stopped, "signed_out")
  assert.equal((await store.list("ama")).filter((c) => c.state === "waiting").length, 2)
  server.signedIn = true
  assert.equal((await store.flush("ama", server.send)).sent.length, 2)
})

test("two accounts on one device never send or see each other's changes or screens", async () => {
  const store = new OfflineStore(new IDBFactory())
  const server = new Server()
  await store.add(change("ama", "ama's"))
  await store.add(change("ben", "ben's"))
  await store.flush("ben", server.send)
  assert.deepEqual(server.made, ["ben's"])
  assert.deepEqual((await store.list("ama")).map((c) => c.label), ["ama's"])
  assert.equal(await store.countAll(), 1)

  await store.saveScreens({ userId: "ama", savedAt: "2026-11-21T10:00:00Z", build: "1", state: { queries: [] } })
  await store.saveScreens({ userId: "ben", savedAt: "2026-11-21T10:00:00Z", build: "1", state: { queries: [] } })
  await store.keepScreensOf("ben")
  assert.equal(await store.loadScreens("ama"), undefined)
  assert.ok(await store.loadScreens("ben"))
  // Ama's waiting change survives Ben signing in: it is hers to send.
  assert.equal((await store.list("ama")).length, 1)

  await store.purge("ama")
  assert.deepEqual(await store.list("ama"), [])
  assert.ok(await store.loadScreens("ben"))
})

test("a change the device can't write is not reported as kept", async () => {
  const factory = new IDBFactory()
  const store = new OfflineStore(factory)
  await store.add(change("ama", "a"))
  const duplicate = (await store.list("ama"))[0]
  await assert.rejects(store.add(duplicate), StorageError) // the write failed: the caller must not say "saved"
  assert.equal((await store.list("ama")).length, 1)

  const broken = new OfflineStore({ open: () => { throw new DOMException("full", "QuotaExceededError") } } as unknown as IDBFactory)
  await assert.rejects(broken.add(change("ama", "b")), (error: Error) => error instanceof StorageError && /full/.test(error.message))
})

test("changes come back after a restart, in the order they were made", async () => {
  const factory = new IDBFactory()
  const first = new OfflineStore(factory)
  for (const label of ["one", "two", "three"]) await first.add(change("ama", label))
  const restarted = new OfflineStore(factory)
  const server = new Server()
  const result = await restarted.flush("ama", server.send)
  assert.deepEqual(result.sent.map((c) => c.label), ["one", "two", "three"])
})
