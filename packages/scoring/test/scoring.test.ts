// Runs the shared fixtures against the TypeScript reducer (REQ-012, EVAL-012):
//   node --experimental-strip-types --test packages/scoring/test/scoring.test.ts
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { Scoring, ScoringError, gamesNeeded, replay, type ScoreEvent, type State } from "../src/index.ts"
import { FIXTURES, canonical, digest, eventsOf, fixtures, type ParityMatch } from "./fixtures.ts"

for (const fixture of fixtures()) {
  test(fixture.name, () => {
    let scoring = new Scoring(fixture.config)
    fixture.steps.forEach((step, number) => {
      const where = `step ${number + 1}`
      if (step.error !== undefined) {
        const before = scoring.state
        assert.throws(
          () => scoring.push(step.event as ScoreEvent),
          (error: unknown) => error instanceof ScoringError && error.code === step.error,
          `${where}: expected ${step.error}`
        )
        assert.equal(scoring.state, before, `${where}: a refused event changes nothing`)
        return
      }
      for (const event of eventsOf(step)) scoring = scoring.push(event)
      for (const [field, value] of Object.entries(step.expect ?? {})) {
        assert.deepEqual(scoring.state[field as keyof State], value, `${where}: ${field}`)
      }
    })
  })
}

test("random legal and illegal streams give the recorded state after every event", () => {
  const matches = JSON.parse(readFileSync(`${FIXTURES}parity.json`, "utf8")) as ParityMatch[]
  assert.ok(matches.length >= 8)
  for (const [number, match] of matches.entries()) {
    let scoring = new Scoring(match.config)
    match.events.forEach((sent, at) => {
      const where = `match ${number + 1}, event ${at + 1} (${canonical(sent.event)})`
      if (sent.error !== undefined) {
        assert.throws(() => scoring.push(sent.event), (error: unknown) => error instanceof ScoringError && error.code === sent.error, where)
        return
      }
      scoring = scoring.push(sent.event)
      assert.equal(digest(scoring.state), sent.digest, `${where}: ${canonical(scoring.state)}`)
    })
  }
})

test("no stream ends in an impossible score", () => {
  const matches = JSON.parse(readFileSync(`${FIXTURES}parity.json`, "utf8")) as ParityMatch[]
  for (const match of matches) {
    const accepted = match.events.filter((sent) => sent.error === undefined).map((sent) => sent.event)
    for (const state of replay(match.config, accepted)) {
      for (const [a, b] of state.games) {
        assert.ok(Math.max(a, b) >= 11 && Math.abs(a - b) >= 2, `finished game ${a}-${b}`)
        assert.ok(Math.max(a, b) === 11 || Math.abs(a - b) === 2, `game ${a}-${b} went on too long`)
      }
      const [a, b] = state.points
      assert.ok(!(Math.max(a, b) >= 11 && Math.abs(a - b) >= 2), `open game at ${a}-${b}`)
      assert.equal(state.games_won[0] + state.games_won[1], state.games.length)
      const needed = gamesNeeded(match.config)
      assert.equal(state.status === "completed", Math.max(...state.games_won) === needed)
      assert.ok(Math.max(...state.games_won) <= needed)
      if (state.status === "in_progress") assert.notEqual(state.server?.[0], state.receiver?.[0], "server and receiver are opponents")
    }
  }
})
