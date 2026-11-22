import { useEffect, useState } from "react"
import { CARD_REASONS, offencesOf, sideOf, type CardReason, type Player, type ScoreEvent, type Side, type State } from "@scoring"
import { CARD_REASON_LABEL, type Names } from "@/lib/scoring"
import { cn } from "@/lib/utils"

const deckButton =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-lg border border-white/30 px-4 text-base font-semibold text-white outline-none hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-brand-cyan disabled:opacity-40"
const warnButton =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-brand-gold px-4 text-base font-bold text-brand-navy outline-none hover:bg-brand-gold/90 focus-visible:ring-3 focus-visible:ring-brand-cyan disabled:opacity-40"

const TIMEOUT_SECONDS = 60 // 3.4.4.2: up to 1 minute
const SUSPENSION_SECONDS = 10 * 60 // 3.4.2.3: up to 10 minutes
const EXPEDITE_RETURNS = 13 // 2.15.4: the receiver wins the point after 13 good returns

/** What the ladder gives for a player's next offence (3.5.2.2-3.5.2.4). */
function nextCard(offences: number): { label: string; points: number } | null {
  if (offences === 0) return { label: "Yellow card: a warning", points: 0 }
  if (offences === 1) return { label: "Yellow and red card: 1 penalty point", points: 1 }
  if (offences === 2) return { label: "Yellow and red card: 2 penalty points", points: 2 }
  return null
}

/** mm:ss of what is left, counted on this device from when the banner first showed. */
function useCountdown(seconds: number) {
  const [started] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const left = Math.max(0, seconds - Math.floor((now - started) / 1000))
  return { left, text: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` }
}

/** A running time-out: its countdown, and resuming play (early when the side is ready). */
export function TimeoutBanner({ state, names, act }: { state: State; names: Names; act: (event: ScoreEvent) => void }) {
  const { left, text } = useCountdown(TIMEOUT_SECONDS)
  const who = (["a", "b"] as const).filter((_, index) => state.timeout_running[index]).map((side) => names[side])
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-cyan/60 bg-brand-cyan/10 p-3">
      <p className="flex-1 font-semibold">
        Time-out: {who.join(" and ")}. <span className="font-display text-2xl tabular-nums">{text}</span>
        {left === 0 && " Time is up."}
      </p>
      <button type="button" className={deckButton} onClick={() => act({ type: "timeout_end" })}>
        Play resumes
      </button>
    </div>
  )
}

/** A suspension for incapacity: its 10-minute countdown, resuming, or the player retiring. */
export function SuspensionBanner({ side, names, act }: { side: Side; names: Names; act: (event: ScoreEvent) => void }) {
  const { left, text } = useCountdown(SUSPENSION_SECONDS)
  const [retiring, setRetiring] = useState(false)
  return (
    <div role="status" className="flex flex-col gap-2 rounded-xl border border-brand-gold/60 bg-brand-gold/10 p-3">
      <p className="font-semibold">
        Play suspended: {names[side]} is injured. <span className="font-display text-2xl tabular-nums">{text}</span>
        {left === 0 && " Ten minutes are up: a player who can't go on retires."}
      </p>
      {retiring ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1">{names[side]} retires: the match goes to the opponent with the points played.</p>
          <button type="button" className={warnButton} onClick={() => act({ type: "retire", side })}>
            Confirm retirement
          </button>
          <button type="button" className={deckButton} onClick={() => setRetiring(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button type="button" className={deckButton} onClick={() => act({ type: "suspension_end" })}>
            Play resumes
          </button>
          <button type="button" className={deckButton} onClick={() => setRetiring(true)}>
            Can't go on: retire
          </button>
        </div>
      )}
    </div>
  )
}

/** The expedite system: service every point, and the receiver's returns counted to 13 (2.15). */
export function ExpediteBar({ state, names, act }: { state: State; names: Names; act: (event: ScoreEvent) => void }) {
  const [returns, setReturns] = useState(0)
  const rally = `${state.game_number}:${state.points[0]}:${state.points[1]}`
  const [counted, setCounted] = useState(rally)
  if (counted !== rally) {
    // A point was scored: the next rally counts from nothing.
    setCounted(rally)
    setReturns(0)
  }
  const receiver = state.receiver ? sideOf(state.receiver) : null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/20 bg-white/5 p-3">
      <p className="flex-1 font-semibold">
        Expedite: service changes every point. Returns by {receiver ? names[receiver] : "the receiver"}:{" "}
        <span className="font-display text-2xl tabular-nums">{returns}</span>
      </p>
      {returns >= EXPEDITE_RETURNS && receiver ? (
        <button type="button" className={warnButton} onClick={() => act({ type: "point", side: receiver })}>
          {EXPEDITE_RETURNS} returns: point to {names[receiver]}
        </button>
      ) : (
        <button type="button" className={deckButton} onClick={() => setReturns(returns + 1)}>
          Return
        </button>
      )}
    </div>
  )
}

type Kind = "card" | "adviser" | "suspension" | "expedite" | "retire" | "disqualify"

/**
 * Incidents the umpire records (REQ-043). Nothing is recorded by a single tap: each choice ends in a
 * confirmation that says what will happen, so a card is never shown by a stray touch.
 */
export function IncidentMenu({ state, names, players, canDisqualify, act }: { state: State; names: Names; players: Player[]; canDisqualify: boolean; act: (event: ScoreEvent) => void }) {
  const [kind, setKind] = useState<Kind | "">("")
  const [player, setPlayer] = useState<Player | "">("")
  const [side, setSide] = useState<Side | "">("")
  const [reason, setReason] = useState<CardReason | "">("")
  const [note, setNote] = useState("")
  const reset = () => {
    setKind("")
    setPlayer("")
    setSide("")
    setReason("")
    setNote("")
  }
  const send = (event: ScoreEvent) => {
    act(event)
    reset()
  }
  if (kind === "")
    return (
      <details className="rounded-xl border border-white/20 bg-white/5">
        <summary className="min-h-12 cursor-pointer px-3 py-3 font-semibold">Incident: card, injury, expedite, retirement</summary>
        <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3">
          <button type="button" className={deckButton} onClick={() => setKind("card")}>
            Player card
          </button>
          <button type="button" className={deckButton} onClick={() => setKind("adviser")}>
            Adviser card
          </button>
          <button type="button" className={deckButton} disabled={state.suspended !== null} onClick={() => setKind("suspension")}>
            Injury suspension
          </button>
          <button type="button" className={deckButton} disabled={state.expedite || state.points[0] + state.points[1] >= 18} onClick={() => setKind("expedite")}>
            Start expedite
          </button>
          <button type="button" className={deckButton} onClick={() => setKind("retire")}>
            Retirement
          </button>
          {canDisqualify && (
            <button type="button" className={deckButton} onClick={() => setKind("disqualify")}>
              Disqualify
            </button>
          )}
        </div>
      </details>
    )

  const sides = (["a", "b"] as const).map((value) => ({ value, label: names[value] }))
  const choose = <T extends string>(label: string, options: { value: T; label: string; disabled?: boolean }[], value: T | "", set: (v: T) => void) => (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-semibold">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button key={option.value} type="button" aria-pressed={value === option.value} disabled={option.disabled} className={cn(deckButton, value === option.value && "border-brand-gold text-brand-gold")} onClick={() => set(option.value)}>
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  )
  const reasons = choose(
    "Why",
    CARD_REASONS.map((value) => ({ value, label: CARD_REASON_LABEL[value] })),
    reason,
    setReason
  )
  const noteField = (
    <label className="flex flex-col gap-1">
      <span className="font-semibold">Note (optional)</span>
      <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} className="min-h-12 rounded-lg border border-white/30 bg-transparent px-3 text-white" />
    </label>
  )
  const withNote = note.trim() ? { note: note.trim() } : {}

  let body = null
  let ready = false
  let confirmText = ""
  let event: ScoreEvent | null = null
  if (kind === "card") {
    const doubles = { doubles: players.length > 2 }
    const ladder = player ? nextCard(offencesOf(doubles, state, player)) : null
    body = (
      <>
        {choose(
          "Which player",
          players.map((value) => ({ value, label: `${names[value]}${state.offences[value] ? ` (${state.offences[value]} so far)` : ""}`, disabled: offencesOf(doubles, state, value) >= 3 })),
          player,
          setPlayer
        )}
        {player && !ladder && <p>A fourth offence is the referee's to decide: call the referee.</p>}
        {reasons}
        {noteField}
      </>
    )
    ready = !!player && !!reason && !!ladder
    confirmText = ladder && player ? `${ladder.label}${ladder.points ? ` to ${names[sideOf(player) === "a" ? "b" : "a"]}` : ""}` : ""
    if (ready && player && reason) event = { type: "card", player, reason, ...withNote }
  } else if (kind === "adviser") {
    const given = side ? state.advisers[side === "a" ? 0 : 1] : 0
    body = (
      <>
        {choose(
          "Whose adviser",
          sides.map((option) => ({ ...option, disabled: state.advisers[option.value === "a" ? 0 : 1] >= 2 })),
          side,
          setSide
        )}
        {reasons}
        {noteField}
      </>
    )
    ready = !!side && !!reason && given < 2
    confirmText = given === 0 ? "Yellow card: a warning to the adviser" : "Red card: the adviser leaves for the rest of the match"
    if (ready && side && reason) event = { type: "adviser_card", side, reason, ...withNote }
  } else if (kind === "suspension" || kind === "retire" || kind === "disqualify") {
    body = choose(kind === "suspension" ? "Who is injured" : kind === "retire" ? "Who retires" : "Who is disqualified", sides, side, setSide)
    ready = !!side
    confirmText =
      kind === "suspension" ? "Suspend play for up to 10 minutes (the referee's decision)" : kind === "retire" ? "Retirement: the match goes to the opponent with the points played" : "Disqualification: the match goes to the opponent with the points played"
    if (side) event = kind === "suspension" ? { type: "suspension", side } : kind === "retire" ? { type: "retire", side } : { type: "disqualify", side }
  } else if (kind === "expedite") {
    body = <p>From now to the end of the match service changes after every point, and the receiver wins the point after {EXPEDITE_RETURNS} good returns.</p>
    ready = true
    confirmText = "Start the expedite system"
    event = { type: "expedite" }
  }

  return (
    <section aria-label="Record an incident" className="flex flex-col gap-3 rounded-xl border border-brand-gold/60 bg-white/5 p-3">
      {body}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={warnButton} disabled={!ready || !event} onClick={() => event && send(event)}>
          {confirmText || "Choose first"}
        </button>
        <button type="button" className={deckButton} onClick={reset}>
          Cancel
        </button>
      </div>
    </section>
  )
}

/** Each side's cards so far, shown under its name. */
export function CardBadges({ state, side, players }: { state: State; side: Side; players: Player[] }) {
  const mine = players.filter((player) => sideOf(player) === side)
  const adviser = state.advisers[side === "a" ? 0 : 1]
  const shown = mine.filter((player) => state.offences[player] > 0)
  if (shown.length === 0 && adviser === 0) return null
  return (
    <span className="flex flex-wrap justify-center gap-1 text-xs font-bold">
      {shown.map((player) => (
        <span key={player} className={cn("rounded px-1.5", state.offences[player] === 1 ? "bg-yellow-400 text-brand-navy" : "bg-red-600 text-white")}>
          <span aria-hidden="true">
            {mine.length > 1 ? `${player.toUpperCase()} ` : ""}
            {state.offences[player] === 1 ? "Y" : `YR${state.offences[player] - 1}`}
          </span>
          <span className="sr-only">
            {player.toUpperCase()}: {state.offences[player] === 1 ? "yellow card" : `yellow and red card, ${state.offences[player] - 1} penalty point${state.offences[player] === 2 ? "" : "s"}`}
          </span>
        </span>
      ))}
      {adviser > 0 && (
        <span className={cn("rounded px-1.5", adviser === 1 ? "bg-yellow-400 text-brand-navy" : "bg-red-600 text-white")}>
          <span aria-hidden="true">Adviser {adviser === 1 ? "Y" : "R"}</span>
          <span className="sr-only">Adviser: {adviser === 1 ? "yellow card" : "red card, sent away"}</span>
        </span>
      )}
    </span>
  )
}

