// Reading the shared fixtures (../fixtures). The Python validator's tests read the same files.
import { createHash } from "node:crypto"
import { readdirSync, readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import type { Config, ScoreEvent, State } from "../src/index.ts"

export interface Step {
  /** A run of points, one letter per point: "aab" is two for side a, then one for side b. */
  points?: string
  event?: ScoreEvent
  /** Fields the state must have after the step. */
  expect?: Partial<State>
  /** The code the event must be refused with; the state stays as it was. */
  error?: string
}

export interface Fixture {
  name: string
  rules: string
  config: Config
  steps: Step[]
}

export interface ParityMatch {
  config: Config
  /** Every event sent, with the code it was refused with, or the digest of the state it led to. */
  events: { event: ScoreEvent; error?: string; digest?: string }[]
}

export const FIXTURES = fileURLToPath(new URL("../fixtures/", import.meta.url))

export const fixtures = (): Fixture[] =>
  readdirSync(FIXTURES)
    .filter((file) => file.startsWith("f-sc") && file.endsWith(".json"))
    .sort()
    .map((file) => JSON.parse(readFileSync(FIXTURES + file, "utf8")) as Fixture)

export const eventsOf = (step: Step): ScoreEvent[] => (step.points !== undefined ? [...step.points].map((side) => ({ type: "point", side }) as ScoreEvent) : [step.event as ScoreEvent])

/** JSON with sorted keys and no spaces: byte for byte what Python's json.dumps(sort_keys=True, separators=(",", ":")) gives. */
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`)
      .join(",")}}`
  }
  return JSON.stringify(value)
}

/** A short fingerprint of a state, the same in both implementations. */
export const digest = (state: State) => createHash("sha256").update(canonical(state)).digest("hex").slice(0, 12)
