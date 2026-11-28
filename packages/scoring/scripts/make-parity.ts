// Writes ../fixtures/parity.json: seeded random score streams (legal and illegal events mixed) with a
// digest of the state after every accepted event, as this reducer computes it. The Python validator's
// tests replay the same streams and must arrive at the same digests, so the two implementations are
// held together on far more sequences than anybody would write by hand. The hand-worked fixtures
// (f-sc*.json) are what say the states are right; this file only says the two agree.
//
//   node --experimental-strip-types packages/scoring/scripts/make-parity.ts
import { writeFileSync } from "node:fs"
import { Scoring, ScoringError, type Config, type Player, type ScoreEvent, type Side } from "../src/index.ts"
import { FIXTURES, digest, type ParityMatch } from "../test/fixtures.ts"

/** mulberry32: a small seeded generator, so the file is the same every time it is made. */
function generator(seed: number) {
  let t = seed
  return () => {
    t = (t + 0x6d2b79f5) | 0
    let x = Math.imul(t ^ (t >>> 15), 1 | t)
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296
  }
}

const CONFIGS: Config[] = [
  { best_of: 3, doubles: false },
  { best_of: 3, doubles: true },
  { best_of: 5, doubles: false },
  { best_of: 5, doubles: true },
  { best_of: 7, doubles: false },
  { best_of: 7, doubles: true },
  // A team tie's later rubbers start with the offences and adviser cards carried from earlier ones.
  { best_of: 5, doubles: false, carry: { offences: { a1: 1, a2: 0, b1: 2, b2: 0 }, advisers: [1, 0] } },
  { best_of: 3, doubles: true, carry: { offences: { a1: 0, a2: 2, b1: 1, b2: 3 }, advisers: [2, 1] } },
]
const REASONS = ["bad_behaviour", "racket_abuse", "illegal_advice", "delay", "other", "shouting"] as const
const PLAYERS: Player[] = ["a1", "a2", "b1", "b2"]

function match(config: Config, seed: number): ParityMatch {
  const random = generator(seed)
  const pick = <T>(items: readonly T[]) => items[Math.floor(random() * items.length)]
  const side = (): Side => (random() < 0.5 ? "a" : "b")
  // Each match leans slightly towards one side, so games are close and deuce is common.
  const lean = 0.42 + random() * 0.16
  const events: ParityMatch["events"] = []
  let scoring = new Scoring(config)

  const send = (event: ScoreEvent) => {
    try {
      scoring = scoring.push(event)
      events.push({ event, digest: digest(scoring.state) })
    } catch (error) {
      if (!(error instanceof ScoringError)) throw error
      events.push({ event, error: error.code })
    }
  }

  const begin = () => {
    const server = config.doubles ? pick(PLAYERS) : pick(["a1", "b1"] as const)
    const receiver = pick(PLAYERS.filter((player) => player[0] !== server[0]))
    send(config.doubles ? { type: "start", server, receiver, a_end: pick(["left", "right"] as const) } : { type: "start", server, a_end: pick(["left", "right"] as const) })
  }

  send({ type: "point", side: "a" }) // refused: not started
  // Now and then a walkover first (sometimes with a reason that isn't one), taken back by an undo.
  if (random() < 0.25) {
    send({ type: "walkover", side: side(), reason: pick(["no_show", "withdrawal", "injury", "late"]) } as ScoreEvent)
    if (scoring.state.status === "completed") send({ type: "undo" })
  }
  begin()
  for (let sent = 0; scoring.state.status !== "completed" && sent < 2000; sent++) {
    const roll = random()
    // An undo can take back the start itself; the umpire then sets the match up again.
    const { status, server, points, game_number } = scoring.state
    if (status === "not_started") {
      // Set up again after an undo took back the start; now and then wrongly first.
      if (roll < 0.3) send({ type: "start", server: "a2", receiver: "a1", a_end: "left" })
      // Now and then a walkover instead, sometimes with a reason that isn't one.
      if (roll > 0.97) send({ type: "walkover", side: side(), reason: pick(["no_show", "withdrawal", "injury", "late"]) } as ScoreEvent)
      else begin()
    }
    // Before a later game of doubles the serving pair often names its other player to serve first.
    else if (config.doubles && server && game_number > 1 && points[0] + points[1] === 0 && roll < 0.5) {
      if (roll < 0.08) send({ type: "choose_server", player: pick(PLAYERS.filter((player) => player[0] !== server[0])) }) // refused
      send({ type: "choose_server", player: pick(PLAYERS.filter((player) => player[0] === server[0])) })
      if (roll > 0.4) send({ type: "undo" }) // takes back the choice, or the last point of the game before
      if (roll > 0.45) send({ type: "timeout", side: side() })
      send({ type: "point", side: random() < lean ? "a" : "b" })
    }
    // A suspension usually ends with play resumed, now and then with the player retiring.
    else if (scoring.state.suspended !== null && roll < 0.6) send(roll < 0.05 ? { type: "retire", side: scoring.state.suspended } : { type: "suspension_end" })
    else if (roll < 0.04) send({ type: "undo" })
    else if (roll < 0.06) send({ type: "timeout", side: side() })
    else if (roll < 0.09) send({ type: "choose_server", player: pick(PLAYERS) })
    else if (roll < 0.1) send({ type: "start", server: "a1", a_end: "left" })
    else if (roll < 0.105) send({ type: "bogus" } as unknown as ScoreEvent)
    else if (roll < 0.11) send({ type: "point", side: "c" } as unknown as ScoreEvent)
    else if (roll < 0.112) send({ type: "walkover", side: side(), reason: "no_show" }) // refused: started
    // Incidents (TASK-083): cards and their penalty points, advisers, time-outs running and ending,
    // suspensions, expedite, and now and then a retirement or a disqualification that ends it all.
    else if (roll < 0.125) send({ type: "card", player: pick(PLAYERS), reason: pick(REASONS) } as ScoreEvent)
    else if (roll < 0.13) send({ type: "adviser_card", side: side(), reason: pick(REASONS) } as ScoreEvent)
    else if (roll < 0.14) send({ type: "timeout_end" })
    else if (roll < 0.145) send({ type: "suspension", side: side() })
    else if (roll < 0.155) send({ type: "suspension_end" })
    else if (roll < 0.158) send({ type: "expedite" })
    else if (roll < 0.1595) send({ type: random() < 0.5 ? "retire" : "disqualify", side: side() })
    else send({ type: "point", side: random() < lean ? "a" : "b" })
  }
  send({ type: "point", side: side() }) // refused: the match is over
  send({ type: "undo" }) // the last point can still be taken back
  return { config, events }
}

const matches = CONFIGS.flatMap((config, index) => [1000, 2000, 3000, 4000].map((seed) => match(config, seed + index)))
writeFileSync(`${FIXTURES}parity.json`, `[\n${matches.map((made) => JSON.stringify(made)).join(",\n")}\n]\n`)
console.log(`${matches.length} matches, ${matches.reduce((total, made) => total + made.events.length, 0)} events`)
