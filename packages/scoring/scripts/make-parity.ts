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
]
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
  begin()
  for (let sent = 0; scoring.state.status !== "completed" && sent < 2000; sent++) {
    const roll = random()
    // An undo can take back the start itself; the umpire then sets the match up again.
    const { status, server, points, game_number } = scoring.state
    if (status === "not_started") begin()
    // Before a later game of doubles the serving pair often names its other player to serve first.
    else if (config.doubles && server && game_number > 1 && points[0] + points[1] === 0 && roll < 0.5) {
      send({ type: "choose_server", player: pick(PLAYERS.filter((player) => player[0] === server[0])) })
      send({ type: "point", side: random() < lean ? "a" : "b" })
    }
    else if (roll < 0.04) send({ type: "undo" })
    else if (roll < 0.06) send({ type: "timeout", side: side() })
    else if (roll < 0.09) send({ type: "choose_server", player: pick(PLAYERS) })
    else if (roll < 0.1) send({ type: "start", server: "a1", a_end: "left" })
    else send({ type: "point", side: random() < lean ? "a" : "b" })
  }
  send({ type: "point", side: side() }) // refused: the match is over
  send({ type: "undo" }) // the last point can still be taken back
  return { config, events }
}

const matches = CONFIGS.flatMap((config, index) => [1000, 2000, 3000].map((seed) => match(config, seed + index)))
writeFileSync(`${FIXTURES}parity.json`, `[\n${matches.map((made) => JSON.stringify(made)).join(",\n")}\n]\n`)
console.log(`${matches.length} matches, ${matches.reduce((total, made) => total + made.events.length, 0)} events`)
