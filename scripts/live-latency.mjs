#!/usr/bin/env node
/**
 * Live score latency trace (REQ-033, REQ-043, TASK-084; reused by the TASK-061 load run).
 *
 * Measures, for each score event an umpire sends, the time from just before the umpire's request leaves to the
 * moment a signed-out viewer holds the new score: the viewer hears the tournament socket name the match, fetches
 * the live list as a live page does, and stops the clock when the list shows the event's revision. Reports p50,
 * p95 and the worst, and exits non-zero when p95 is over the target.
 *
 * Use a match set aside for it: the script takes the sheet over (cutting off any other device), then sends a
 * point and its undo, again and again, so the score ends where it started.
 *
 *   node scripts/live-latency.mjs --base http://localhost:8090 --scorecard <id> \
 *        --login umpire@mombasa-tt.test [--view list|match] [--count 60] [--target 2000] [--gap 250]
 *
 * --view list (the default) reads the tournament's live list, as the score strip and live page do; --view match
 * reads the match page's data. One viewer and one sheet: the 8-table, 100-viewer run of EVAL-033 is TASK-061's.
 *
 * The password is read from LIVE_TRACE_PASSWORD, never from the command line, so it stays out of shell history.
 * --base is the site's origin; the API is under /api/v1 and the socket under /api/v1/ws. Node 22 or later.
 */
import { randomUUID } from "node:crypto"
import { parseArgs } from "node:util"

const { values: args } = parseArgs({
  options: {
    base: { type: "string", default: "http://localhost:8090" },
    scorecard: { type: "string" },
    login: { type: "string" },
    count: { type: "string", default: "60" },
    target: { type: "string", default: "2000" },
    gap: { type: "string", default: "250" },
    view: { type: "string", default: "list" },
    timeout: { type: "string", default: "10000" },
  },
})
const password = process.env.LIVE_TRACE_PASSWORD
if (!args.scorecard || !args.login || !password) {
  console.error("Needs --scorecard, --login and LIVE_TRACE_PASSWORD in the environment.")
  process.exit(2)
}
const origin = new URL(args.base).origin
const api = `${origin}/api/v1`
const count = Number(args.count)
const target = Number(args.target)
const gap = Number(args.gap)
const timeout = Number(args.timeout)
const REQUEST_TIMEOUT = 10_000

/** A tiny cookie jar for the umpire's session, and Django's CSRF header for writes. */
const jar = new Map()
function remember(response) {
  for (const cookie of response.headers.getSetCookie?.() ?? []) {
    const [pair] = cookie.split(";")
    const at = pair.indexOf("=")
    jar.set(pair.slice(0, at), pair.slice(at + 1))
  }
}
async function call(path, { method = "GET", body, headers = {}, signedIn = true } = {}) {
  const sent = { ...headers, Origin: origin, Referer: `${origin}/` }
  if (signedIn && jar.size) sent.Cookie = [...jar].map(([name, value]) => `${name}=${value}`).join("; ")
  if (method !== "GET") sent["X-CSRFToken"] = jar.get("csrftoken") ?? ""
  if (body !== undefined) sent["Content-Type"] = "application/json"
  const response = await fetch(`${api}${path}`, { method, headers: sent, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(REQUEST_TIMEOUT) })
  if (signedIn) remember(response)
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${text.slice(0, 200)}`)
  return data
}

const percentile = (sorted, p) => sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)]
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function main() {
  await call("/auth/csrf/")
  await call("/auth/login/", { method: "POST", body: { login: args.login, password } })
  const device = randomUUID()
  const deviceHeaders = { "X-Device-Id": device }
  let sheet = await call(`/scorecards/${args.scorecard}/device/`, { method: "POST", body: { device_id: device, label: "Latency trace", take_over: true }, headers: deviceHeaders })
  const { tournament_id: tournamentId, event_id: eventId, match_id: matchId } = sheet
  /** The revision the viewer holds now, read the way the chosen view reads it. */
  async function shownRevision() {
    if (args.view === "match") {
      const match = await call(`/tournaments/${tournamentId}/events/${eventId}/matches/${matchId}/`, { signedIn: false })
      const rubber = match.tie?.rubbers.find((candidate) => candidate.scoring?.live)
      return (match.scoring?.live ?? rubber?.scoring?.live)?.revision ?? 0
    }
    const live = await call(`/tournaments/${tournamentId}/live/`, { signedIn: false })
    return live.find((shown) => shown.match_id === matchId)?.score.revision ?? 0
  }
  let revision = sheet.revision

  async function send(event) {
    revision += 1
    const reply = await call(`/scorecards/${args.scorecard}/events/`, {
      method: "POST",
      headers: deviceHeaders,
      body: { assignment_id: sheet.assignment_id, events: [{ id: randomUUID(), sequence: revision, expected_revision: revision - 1, event }] },
    })
    if (reply.refused) throw new Error(`refused: ${JSON.stringify(reply.refused)}`)
    return revision
  }
  if (sheet.state.status === "not_started") await send({ type: "start", server: "a1", a_end: "left" })
  if (sheet.state.status === "completed") throw new Error("This sheet's match is over: use a match still to be played.")

  // The viewer: signed out, listening on the tournament's socket, fetching the live list as a live page does.
  const socketUrl = `${api.replace(/^http/, "ws")}/ws/tournaments/${tournamentId}/`
  const socket = new WebSocket(socketUrl, { headers: { Origin: origin } })
  let opening
  await new Promise((resolve, reject) => {
    socket.onopen = resolve
    socket.onerror = () => reject(new Error(`Could not open ${socketUrl}`))
    opening = setTimeout(() => reject(new Error("The socket didn't open in time.")), timeout)
  }).finally(() => clearTimeout(opening))
  let waiting = null
  socket.onmessage = async (frame) => {
    try {
      const message = JSON.parse(String(frame.data))
      if (message.type !== "changed" || message.match !== matchId || !waiting) return
      const revision = await shownRevision()
      if (waiting && revision >= waiting.revision) {
        waiting.resolve(performance.now())
        waiting = null
      }
    } catch (error) {
      waiting?.reject(error)
      waiting = null
    }
  }

  const times = []
  for (let n = 0; n < count; n++) {
    const event = n % 2 === 0 ? { type: "point", side: "a" } : { type: "undo" }
    const started = performance.now()
    let timer
    const seen = new Promise((resolve, reject) => {
      waiting = { revision: revision + 1, resolve, reject }
      timer = setTimeout(() => reject(new Error(`No viewer update for event ${n + 1} within ${timeout} ms`)), timeout)
    })
    await send(event)
    try {
      times.push((await seen) - started)
    } finally {
      clearTimeout(timer)
    }
    await sleep(gap)
  }
  // An odd count leaves the last point standing: take it back.
  if (count % 2 === 1) await send({ type: "undo" })
  socket.close()
  await call("/auth/logout/", { method: "POST" })

  const sorted = [...times].sort((a, b) => a - b)
  const result = { view: args.view, events: times.length, p50_ms: Math.round(percentile(sorted, 50)), p95_ms: Math.round(percentile(sorted, 95)), max_ms: Math.round(sorted.at(-1)), target_p95_ms: target }
  console.log(JSON.stringify(result, null, 2))
  process.exit(result.p95_ms <= target ? 0 : 1)
}

main().catch((error) => {
  console.error(error.message)
  process.exit(2)
})
