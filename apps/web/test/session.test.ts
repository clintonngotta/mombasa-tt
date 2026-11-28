// Staying signed in without a connection (REQ-035):
//   node --experimental-strip-types --test test/session.test.ts
import assert from "node:assert/strict"
import { test } from "node:test"
import { checkSession, sessionEnded } from "../src/lib/sessionCheck.ts"

const amina = { id: "u-1", email: "amina@example.com" }
const status = (code: number) => Object.assign(new Error(`API request failed with ${code}`), { status: code })

test("a lost connection keeps the account the device knew", async () => {
  const offline = () => Promise.reject(new TypeError("Failed to fetch"))
  assert.deepEqual(await checkSession(offline, amina), amina)
})

test("a server error or a proxy page keeps it too", async () => {
  for (const code of [500, 502, 503, 504, 429]) {
    assert.deepEqual(await checkSession(() => Promise.reject(status(code)), amina), amina)
  }
})

test("the server saying the session ended signs out", async () => {
  for (const code of [401, 403]) {
    assert.equal(sessionEnded(status(code)), true)
    await assert.rejects(checkSession(() => Promise.reject(status(code)), amina), { status: code })
  }
})

test("with no known account, a failure is a failure", async () => {
  await assert.rejects(checkSession(() => Promise.reject(new TypeError("Failed to fetch")), undefined), TypeError)
})

test("an answer replaces what was known", async () => {
  const bea = { id: "u-2", email: "bea@example.com" }
  assert.deepEqual(await checkSession(() => Promise.resolve(bea), amina), bea)
})
