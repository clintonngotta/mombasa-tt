import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, CircleCheck, Undo2 } from "lucide-react"
import { Scoring, gamesNeeded, partnerOf, sideOf, type Config, type End, type Player, type ScoreEvent, type Side, type State } from "@scoring"
import { errorMessage } from "@/lib/api"
import { createMatch, matchKeys } from "@/lib/matchlog"
import { getMe, meQueryKey } from "@/lib/session"
import { cn } from "@/lib/utils"

// Quick Score (REQ-017): a casual game scored on this device with the same rules as official scoring,
// with no tournament, no rating and no table booking. It lives in this browser's storage, so it works
// signed out and offline and survives a reload. A signed-in player can save the finished game to their
// own match log, labelled as recorded by them; saving twice keeps one record.

const STORE = "coast-tt-quick-score"
type Names = Record<Player, string>
type Game = { id: string; config: Config; names: Names; events: ScoreEvent[]; startedOn: string; savedId?: string }

const deckButton =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-lg border border-white/30 px-4 text-base font-semibold text-white outline-none hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-brand-cyan disabled:opacity-40"
const primaryButton =
  "inline-flex min-h-14 items-center justify-center gap-2 rounded-lg bg-brand-gold px-6 text-lg font-bold text-brand-navy outline-none hover:bg-brand-gold/90 focus-visible:ring-3 focus-visible:ring-brand-cyan disabled:opacity-40"
const input = "min-h-12 w-full rounded-lg border border-white/30 bg-white/10 px-3 text-base text-white placeholder:text-white/50 outline-none focus-visible:ring-3 focus-visible:ring-brand-cyan"

const newId = () => (typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`)
const today = () => new Date().toLocaleDateString("en-CA") // YYYY-MM-DD in the device's own day

function load(): Game | null {
  try {
    const kept = localStorage.getItem(STORE)
    return kept ? (JSON.parse(kept) as Game) : null
  } catch {
    return null
  }
}

function keep(game: Game | null) {
  try {
    if (game) localStorage.setItem(STORE, JSON.stringify(game))
    else localStorage.removeItem(STORE)
  } catch {
    // Private mode or full storage: the game goes on, it just won't survive a reload.
  }
}

/** The game as the events left it. An event the rules refuse is dropped, so a bad tap changes nothing. */
function play(game: Game): Scoring {
  let scoring = new Scoring(game.config)
  for (const event of game.events) {
    try {
      scoring = scoring.push(event)
    } catch {
      // stored by an older version, or refused: skip it
    }
  }
  return scoring
}

const sideName = (names: Names, side: Side, doubles: boolean) => (doubles ? `${names[`${side}1`]} & ${names[`${side}2`]}` : names[`${side}1`])

export function QuickScorePage() {
  const [game, setGame] = useState<Game | null>(load)
  useEffect(() => keep(game), [game])
  const scoring = useMemo(() => (game ? play(game) : null), [game])

  return (
    <div className="flex min-h-dvh flex-col bg-brand-navy text-white">
      <header className="flex items-center gap-3 border-b border-white/15 px-3 py-2">
        <Link to="/play" aria-label="Leave Quick Score" className="flex size-12 shrink-0 items-center justify-center rounded-lg outline-none hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-brand-cyan">
          <ArrowLeft aria-hidden className="size-6" />
        </Link>
        <div className="flex min-w-0 flex-1 flex-col">
          <p className="truncate font-semibold">Quick Score</p>
          <p className="truncate text-sm text-white/70">Casual: no rating, no standings, no table booking</p>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-4 p-3">
        {!game || !scoring ? (
          <Setup onStart={setGame} />
        ) : (
          <Deck
            game={game}
            scoring={scoring}
            act={(event) => setGame({ ...game, events: [...game.events, event] })}
            onSaved={(savedId) => setGame({ ...game, savedId })}
            onNew={() => setGame(null)}
          />
        )}
      </main>
    </div>
  )
}

function Choice<T extends string>({ legend, options, value, onChange }: { legend: string; options: { value: T; label: string }[]; value: T | ""; onChange: (value: T) => void }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-lg font-semibold">{legend}</legend>
      <div className="grid grid-cols-2 gap-2">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
            className={cn(deckButton, "min-h-14 break-words whitespace-normal", value === option.value && "border-brand-gold bg-brand-gold text-brand-navy hover:bg-brand-gold")}
          >
            {option.label}
          </button>
        ))}
      </div>
    </fieldset>
  )
}

function Setup({ onStart }: { onStart: (game: Game) => void }) {
  const [doubles, setDoubles] = useState<"singles" | "doubles">("singles")
  const [bestOf, setBestOf] = useState<"3" | "5" | "7">("5")
  const [names, setNames] = useState<Names>({ a1: "", a2: "", b1: "", b2: "" })
  const [server, setServer] = useState<Player | "">("")
  const [receiver, setReceiver] = useState<Player | "">("")
  const [left, setLeft] = useState<Side | "">("")
  const isDoubles = doubles === "doubles"
  const slots: Player[] = isDoubles ? ["a1", "a2", "b1", "b2"] : ["a1", "b1"]
  const label = (player: Player) => names[player].trim() || (isDoubles ? `Player ${player.toUpperCase()}` : player === "a1" ? "Player A" : "Player B")
  const filled: Names = { a1: label("a1"), a2: label("a2"), b1: label("b1"), b2: label("b2") }
  const ready = server && left && (!isDoubles || receiver)

  return (
    <section aria-labelledby="quick-setup" className="flex flex-col gap-5 rounded-xl border border-white/20 bg-white/5 p-4">
      <div>
        <h1 id="quick-setup" className="text-2xl font-bold">
          Score a casual game
        </h1>
        <p className="text-white/80">Names are just labels: they don't link to anyone's profile.</p>
      </div>
      <Choice legend="Game" options={[{ value: "singles", label: "Singles" }, { value: "doubles", label: "Doubles" }]} value={doubles} onChange={(value) => { setDoubles(value); setServer(""); setReceiver("") }} />
      <Choice legend="Best of" options={[{ value: "3", label: "3 games" }, { value: "5", label: "5 games" }, { value: "7", label: "7 games" }]} value={bestOf} onChange={setBestOf} />
      <div className="grid grid-cols-2 gap-3">
        {slots.map((slot) => (
          <label key={slot} className="flex flex-col gap-1">
            <span className="text-sm font-semibold">{sideOf(slot) === "a" ? "Side A" : "Side B"}{isDoubles ? `, player ${slot[1]}` : ""}</span>
            <input className={input} maxLength={40} value={names[slot]} placeholder={label(slot)} onChange={(e) => setNames({ ...names, [slot]: e.target.value })} />
          </label>
        ))}
      </div>
      <Choice legend="Who serves first?" options={slots.map((slot) => ({ value: slot, label: filled[slot] }))} value={server} onChange={(player) => { setServer(player); setReceiver("") }} />
      {isDoubles && server && (
        <Choice legend="Who receives first?" options={slots.filter((slot) => sideOf(slot) !== sideOf(server)).map((slot) => ({ value: slot, label: filled[slot] }))} value={receiver} onChange={setReceiver} />
      )}
      <Choice legend="Who starts at the left end, as you see the table?" options={[{ value: "a" as Side, label: sideName(filled, "a", isDoubles) }, { value: "b" as Side, label: sideName(filled, "b", isDoubles) }]} value={left} onChange={setLeft} />
      <button
        type="button"
        className={cn(primaryButton, "self-start")}
        disabled={!ready}
        onClick={() => {
          if (!server || !left) return
          const start: ScoreEvent = { type: "start", server, ...(isDoubles && receiver ? { receiver } : {}), a_end: (left === "a" ? "left" : "right") as End }
          onStart({ id: newId(), config: { best_of: Number(bestOf) as Config["best_of"], doubles: isDoubles }, names: filled, events: [start], startedOn: today() })
        }}
      >
        Start
      </button>
    </section>
  )
}

function Deck({ game, scoring, act, onSaved, onNew }: { game: Game; scoring: Scoring; act: (event: ScoreEvent) => void; onSaved: (id: string) => void; onNew: () => void }) {
  const state = scoring.state
  const { names, config } = game
  const finished = state.status === "completed"
  const order: Side[] = state.a_end === "right" ? ["b", "a"] : ["a", "b"]
  const choosing = config.doubles && !finished && state.game_number > 1 && state.points[0] + state.points[1] === 0 && state.server
  const safe = (event: ScoreEvent) => {
    try {
      scoring.push(event)
      act(event)
    } catch {
      // not allowed now: nothing happens
    }
  }

  return (
    <>
      <section aria-label="Score" className="overflow-hidden rounded-xl border border-white/20 bg-white/5">
        <p className="border-b border-white/15 px-3 py-1.5 text-center text-sm font-semibold text-white/80">
          {finished ? "Game over" : `Game ${state.game_number} · first to ${gamesNeeded(config)} games`}
        </p>
        <div className="grid grid-cols-2 divide-x divide-white/20">
          {order.map((side) => (
            <SidePanel key={side} side={side} state={state} names={names} doubles={config.doubles} live={!finished} onPoint={() => safe({ type: "point", side })} />
          ))}
        </div>
        {state.games.length > 0 && (
          <p className="border-t border-white/15 px-3 py-1.5 text-center text-sm tabular-nums text-white/80">Games: {state.games.map((points) => points.join("–")).join(", ")}</p>
        )}
      </section>
      {choosing && state.server && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/20 bg-white/5 p-3">
          <p className="flex-1 font-semibold">Who serves first in this game?</p>
          {[state.server, partnerOf(state.server)].sort().map((player) => (
            <button key={player} type="button" aria-pressed={state.server === player} className={cn(deckButton, state.server === player && "border-brand-gold text-brand-gold")} onClick={() => safe({ type: "choose_server", player })}>
              {names[player]}
            </button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <button type="button" className={deckButton} disabled={scoring.undoable <= 1} onClick={() => safe({ type: "undo" })}>
          <Undo2 aria-hidden className="size-5" /> Undo
        </button>
        <button type="button" className={deckButton} onClick={onNew}>
          {finished ? "New game" : "Start over"}
        </button>
      </div>
      {finished && state.winner && <Finished game={game} state={state} onSaved={onSaved} />}
    </>
  )
}

function SidePanel({ side, state, names, doubles, live, onPoint }: { side: Side; state: State; names: Names; doubles: boolean; live: boolean; onPoint: () => void }) {
  const index = side === "a" ? 0 : 1
  const serving = state.server !== null && sideOf(state.server) === side
  return (
    <button type="button" disabled={!live} onClick={onPoint} aria-label={`Point to ${sideName(names, side, doubles)}`} className="flex min-h-[40vh] flex-col items-center justify-center gap-2 p-4 outline-none hover:bg-white/5 focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-brand-cyan disabled:hover:bg-transparent">
      <span className="text-center text-lg font-semibold break-words">{sideName(names, side, doubles)}</span>
      <span className="text-[min(28vw,10rem)] leading-none font-bold tabular-nums">{state.points[index]}</span>
      <span className="text-white/80">Games {state.games_won[index]}</span>
      {serving && live && <span className="rounded-full bg-brand-gold px-3 py-1 text-sm font-bold text-brand-navy">Serving{doubles && state.server ? `: ${names[state.server]}` : ""}</span>}
    </button>
  )
}

function Finished({ game, state, onSaved }: { game: Game; state: State; onSaved: (id: string) => void }) {
  const me = useQuery({ queryKey: meQueryKey, queryFn: getMe, retry: false })
  const queryClient = useQueryClient()
  const { names, config } = game
  const [mine, setMine] = useState<Player | "">("")
  const winner = sideName(names, state.winner ?? "a", config.doubles)
  const slots: Player[] = config.doubles ? ["a1", "a2", "b1", "b2"] : ["a1", "b1"]
  const save = useMutation({
    mutationFn: () => {
      if (!mine) throw new Error("Choose who you were.")
      const own = sideOf(mine)
      const other: Side = own === "a" ? "b" : "a"
      return createMatch({
        played_on: game.startedOn,
        label: "Quick Score",
        format: config.doubles ? "doubles" : "singles",
        opponent_name: sideName(names, other, config.doubles),
        partner_name: config.doubles ? names[partnerOf(mine)] : "",
        venue: "",
        notes: "",
        games: state.games.map(([a, b]) => (own === "a" ? { my_points: a, opponent_points: b } : { my_points: b, opponent_points: a })),
        client_ref: game.id,
        source: "quick_score",
      })
    },
    onSuccess: (saved) => {
      onSaved(saved.id)
      void queryClient.invalidateQueries({ queryKey: matchKeys.all })
    },
  })

  return (
    <section aria-labelledby="quick-finished" className="flex flex-col gap-4 rounded-xl border border-white/20 bg-white/5 p-4">
      <h2 id="quick-finished" className="flex items-center gap-2 text-xl font-bold">
        <CircleCheck aria-hidden className="size-6 text-brand-gold" /> {winner} won {Math.max(...state.games_won)}–{Math.min(...state.games_won)}
      </h2>
      {game.savedId ? (
        <p>
          Saved to your match log as a game you recorded.{" "}
          <Link to={`/matches/${game.savedId}`} className="font-semibold text-brand-gold underline-offset-4 hover:underline">
            Open it
          </Link>
        </p>
      ) : me.data ? (
        <>
          <Choice legend="Save it to your match log: who were you?" options={slots.map((slot) => ({ value: slot, label: names[slot] }))} value={mine} onChange={setMine} />
          <p className="text-sm text-white/70">Only you see your match log. A casual game never changes ratings, rankings or tournament results.</p>
          <button type="button" className={cn(primaryButton, "self-start")} disabled={!mine || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save to my match log"}
          </button>
          {save.isError && <p role="alert" className="font-semibold text-brand-gold">{errorMessage(save.error, "We couldn't save it. It's still here: try again when you're connected.")}</p>}
        </>
      ) : (
        <p>
          <Link to="/login?next=/quick-score" className="font-semibold text-brand-gold underline-offset-4 hover:underline">
            Log in
          </Link>{" "}
          to save this game to your match log. It stays on this device until you start a new one.
        </p>
      )}
    </section>
  )
}
