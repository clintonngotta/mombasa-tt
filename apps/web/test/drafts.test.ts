// Form drafts kept on the device, run under Node with a stand-in localStorage:
//   node --experimental-strip-types --test test/drafts.test.ts
import assert from "node:assert/strict"
import { test } from "node:test"
import { fits, forgetDrafts, MAX_DRAFT_BYTES, MAX_DRAFTS, readDraft, removeDraft, writeDraft } from "../src/lib/drafts.ts"

class Memory {
  items = new Map<string, string>()
  get length() {
    return this.items.size
  }
  key = (index: number) => [...this.items.keys()][index] ?? null
  getItem = (key: string) => this.items.get(key) ?? null
  setItem = (key: string, value: string) => void this.items.set(key, value)
  removeItem = (key: string) => void this.items.delete(key)
}

const DAY = 86_400_000

test("a draft comes back for the same account and form only", () => {
  const store = new Memory()
  assert.equal(writeDraft(store, "ann", "tournament:new", { name: "Coast Open", paid: true }, 1000), true)
  assert.deepEqual(readDraft(store, "ann", "tournament:new", 2000), { at: 1000, values: { name: "Coast Open", paid: true } })
  assert.equal(readDraft(store, "ben", "tournament:new", 2000), null)
  assert.equal(readDraft(store, "ann", "event:new", 2000), null)
})

test("one account's id can't reach into another's drafts by its prefix", () => {
  const store = new Memory()
  writeDraft(store, "ann", "note", { text: "hers" })
  writeDraft(store, "an", "n.note", { text: "his" })
  forgetDrafts(store, "an")
  assert.deepEqual(readDraft(store, "ann", "note")?.values, { text: "hers" })
})

test("a draft is dropped after thirty days, when removed, and when the account logs out", () => {
  const store = new Memory()
  writeDraft(store, "ann", "a", { text: "one" }, 0)
  assert.ok(readDraft(store, "ann", "a", 30 * DAY))
  assert.equal(readDraft(store, "ann", "a", 30 * DAY + 1), null)
  assert.equal(store.length, 0, "an expired draft is removed, not left on the device")

  writeDraft(store, "ann", "a", { text: "one" })
  removeDraft(store, "ann", "a")
  assert.equal(readDraft(store, "ann", "a"), null)

  writeDraft(store, "ann", "a", { text: "one" })
  writeDraft(store, "ann", "b", { text: "two" })
  writeDraft(store, "ben", "a", { text: "his" })
  forgetDrafts(store, "ann")
  assert.equal(readDraft(store, "ann", "a"), null)
  assert.equal(readDraft(store, "ann", "b"), null)
  assert.deepEqual(readDraft(store, "ben", "a")?.values, { text: "his" })
})

test("a draft that is too long is refused and the earlier one stays", () => {
  const store = new Memory()
  writeDraft(store, "ann", "a", { text: "short" }, 1)
  assert.equal(writeDraft(store, "ann", "a", { text: "x".repeat(MAX_DRAFT_BYTES) }, 2), false)
  assert.deepEqual(readDraft(store, "ann", "a", 3)?.values, { text: "short" })
})

test("an account keeps a bounded number of drafts, the oldest going first", () => {
  const store = new Memory()
  for (let i = 0; i < MAX_DRAFTS + 5; i += 1) writeDraft(store, "ann", `form-${i}`, { i }, 1000 + i)
  assert.equal(store.length, MAX_DRAFTS)
  assert.equal(readDraft(store, "ann", "form-0", 2000), null)
  assert.ok(readDraft(store, "ann", `form-${MAX_DRAFTS + 4}`, 2000))
})

test("damaged or hand-edited storage reads as no draft", () => {
  const store = new Memory()
  for (const raw of ["not json", "null", "[]", '{"at":"soon","values":{}}', '{"at":1,"values":[1]}', '{"at":1}']) {
    store.setItem("coasttt.draft.ann.a", raw)
    assert.equal(readDraft(store, "ann", "a", 2), null, raw)
  }
})

test("storage that throws never breaks the form", () => {
  const broken = {
    length: 0,
    key: () => null,
    getItem: () => {
      throw new Error("blocked")
    },
    setItem: () => {
      throw new Error("full")
    },
    removeItem: () => {
      throw new Error("blocked")
    },
  }
  assert.equal(readDraft(broken, "ann", "a"), null)
  assert.equal(writeDraft(broken, "ann", "a", { text: "one" }), false)
  removeDraft(broken, "ann", "a")
  forgetDrafts(broken, "ann")
})

test("a kept value only stands in for a field of the same kind", () => {
  assert.equal(fits("text", ""), true)
  assert.equal(fits(3, ""), false)
  assert.equal(fits(undefined, ""), false)
  assert.equal(fits(null, ""), false)
  assert.equal(fits(true, false), true)
  assert.equal(fits(["a"], [] as string[]), true)
  assert.equal(fits("a", [] as string[]), false)
  assert.equal(fits([1], ["a"]), false)
  assert.equal(fits([{ label: "A", places: "4" }], [{ label: "", places: "4" }]), true)
  assert.equal(fits([{ label: 7 }], [{ label: "", places: "4" }]), false)
  assert.equal(fits({ name: "A" }, { name: "", email: "" }), true, "a key the draft lacks keeps its starting value")
  assert.equal(fits({ name: ["A"] }, { name: "" }), false)
  assert.equal(fits([], { name: "" }), false)
  assert.equal(fits("text", null), true)
  assert.equal(fits({ a: 1 }, null), false)
})
