/**
 * Live views never render umpire controls (REQ-010, REQ-043, TASK-084). The live score, the score strip and the
 * live page only read: they may not import the deck, the umpire's or the organizers' controls, link to the deck,
 * or offer a button or a form. The API side is tests/test_live_scores.py (nothing the deck scores with is sent).
 */
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"

const LIVE_VIEWS = ["src/components/tournaments/LiveScore.tsx", "src/pages/tournaments/LivePage.tsx"]
const CONTROLS = [/components\/scoring\//, /lib\/deck/, /UmpireControl/, /ResultControl/, /TableControl/, /ScoringDeck/, /sendEvents|confirmScore|takeDevice/]

const source = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8")
const imports = (text: string) => [...text.matchAll(/^import .* from "([^"]+)"/gm)].map((found) => found[0])

for (const path of LIVE_VIEWS) {
  test(`${path} imports no scoring or umpire control`, () => {
    for (const line of imports(source(path))) for (const control of CONTROLS) assert.doesNotMatch(line, control, line)
  })

  test(`${path} offers nothing to press but links, and never the deck`, () => {
    const text = source(path)
    assert.doesNotMatch(text, /<button|<form|<input|<select|onClick=/)
    assert.doesNotMatch(text, /\/score\//)
  })
}

test("the match page's live score is the read-only component", () => {
  const page = source("src/pages/tournaments/MatchPage.tsx")
  const at = page.indexOf("function Live(")
  assert.ok(at >= 0, "MatchPage has its Live component")
  const live = page.slice(at)
  assert.ok(live.includes("<LiveScoreboard"))
  assert.doesNotMatch(live, /UmpireControl|ResultControl|<button|onClick=/)
})
