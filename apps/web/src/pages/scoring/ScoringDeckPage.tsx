import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowLeftRight, CircleCheck, CloudOff, LoaderCircle, Undo2, WifiOff } from "lucide-react"
import { gamesNeeded, partnerOf, sideOf, type End, type Player, type Side, type State } from "@scoring"
import { errorMessage } from "@/lib/api"
import { describeLog, problemText, useDeck, type LogLine, type Sync } from "@/lib/deck"
import { useMe } from "@/lib/session"
import { drawKeys } from "@/lib/draws"
import { configOf, confirmScorecard, namesOf, scoringKeys, winnersGames, winnersScore, type Names, type Scorecard } from "@/lib/scoring"
import { cn } from "@/lib/utils"
import { UpdateBanner } from "@/components/layout/UpdateBanner"
import { useAppUpdate } from "@/lib/pwa"

const deckButton =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-lg border border-white/30 px-4 text-base font-semibold text-white outline-none hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-brand-cyan disabled:opacity-40"
const primaryButton =
  "inline-flex min-h-14 items-center justify-center gap-2 rounded-lg bg-brand-gold px-6 text-lg font-bold text-brand-navy outline-none hover:bg-brand-gold/90 focus-visible:ring-3 focus-visible:ring-brand-cyan disabled:opacity-40"

/**
 * The umpire's scoring deck (REQ-012): full screen, navy, the two sides left and right as they stand at
 * the table. Tapping a side's panel gives it the point. Only the umpire assigned to the match reaches
 * this page; the result is official once they confirm a finished match and the server accepts it.
 */
export function ScoringDeckRoute() {
  const { id = "" } = useParams()
  const me = useMe()
  if (!me.data) return null // RequireAuth has loaded the account before this route renders
  // A deck belongs to one sheet and one account: another of either is another deck.
  return <ScoringDeckPage key={`${me.data.id}:${id}`} id={id} userId={me.data.id} />
}

function ScoringDeckPage({ id, userId }: { id: string; userId: string }) {
  const deck = useDeck(id, userId)
  const { card, state } = deck
  // Only an out-of-date app is offered an update here: a routine one waits until scoring is done.
  const { outdated } = useAppUpdate()
  const back = card ? `/tournaments/${card.tournament_id}/events/${card.event_id}/matches/${card.match_id}` : "/play"

  return (
    <div className="flex min-h-dvh flex-col bg-brand-navy text-white">
      <header className="flex items-center gap-3 border-b border-white/15 px-3 py-2">
        <Link to={back} aria-label="Leave the scoring deck" className="flex size-12 shrink-0 items-center justify-center rounded-lg outline-none hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-brand-cyan">
          <ArrowLeft aria-hidden className="size-6" />
        </Link>
        <div className="flex min-w-0 flex-1 flex-col">
          <p className="truncate font-semibold">{card ? `${card.event_name} · ${card.label}` : "Scoring"}</p>
          <p className="truncate text-sm text-white/70">{card ? [card.tournament_name, card.table].filter(Boolean).join(" · ") : " "}</p>
        </div>
        {card && !card.confirmed_at && <SyncChip sync={deck.sync} pending={deck.pending} onRetry={deck.retry} />}
      </header>

      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-4 p-3">
        {outdated && <UpdateBanner />}
        {!card && !deck.lost && !deck.failure && (
          <p role="status" className="flex items-center gap-2 text-white/80">
            <LoaderCircle aria-hidden className="size-5 animate-spin" /> Loading the match…
          </p>
        )}
        {deck.lost && (
          <Message title="This match isn't yours to score">
            It may have been given to another umpire or to another device, or it doesn't exist. Nothing more can be scored from here.
          </Message>
        )}
        {!!deck.failure && !deck.lost && (
          <Message title="We couldn't load the match">
            {errorMessage(deck.failure)}{" "}
            <button type="button" className={cn(deckButton, "mt-3 flex")} onClick={() => void deck.reload()}>
              Try again
            </button>
          </Message>
        )}
        {deck.readOnly && !deck.lost && (
          <Message title="Open in another tab">This match is being scored in another tab or window on this device. This one only shows the score; it takes over by itself if the other is closed.</Message>
        )}
        {deck.elsewhere !== null && !deck.lost && card && !card.confirmed_at && (
          <div role="alert" className="flex flex-col gap-2 rounded-xl border border-white/20 bg-white/5 p-4">
            <h1 className="text-2xl font-bold">Being scored on another device</h1>
            <p className="text-white/80">
              {deck.elsewhere ? `${deck.elsewhere} has this match.` : "Another device has this match."} This one only shows the score. Taking it over moves the scoring here: the other device can send nothing
              more, and anything it hadn't sent yet is kept on it and reported to the organizers, not added to the score.
            </p>
            <button type="button" className={cn(primaryButton, "self-start")} onClick={() => void deck.takeOver()}>
              Take over on this device
            </button>
          </div>
        )}
        {deck.offline && !deck.lost && (
          <p role="status" className="flex items-start gap-2 rounded-lg border border-white/30 bg-white/5 p-3">
            <WifiOff aria-hidden className="mt-0.5 size-5 shrink-0" />
            <span>No connection to Coast TT. You can go on scoring: every action is kept on this device and sent when the connection is back. The result can be confirmed once everything has been sent.</span>
          </p>
        )}
        {deck.storageFailed && (
          <p role="alert" className="rounded-lg border border-brand-gold bg-brand-gold/10 p-3 font-semibold text-brand-gold">
            This device can't save score actions right now (storage is full, blocked or in private browsing). Nothing is shown as scored unless it was saved.
          </p>
        )}
        {deck.conflicts > 0 && (
          <div role="alert" className="flex flex-col gap-2 rounded-lg border border-brand-gold/60 bg-brand-gold/10 p-3 text-brand-gold">
            <p>
              {deck.conflicts} {deck.conflicts === 1 ? "action" : "actions"} scored on this device {deck.conflicts === 1 ? "was" : "were"} not accepted by the server (the match was reassigned, scored from somewhere else first, or the server refused
              the action). {deck.conflicts === 1 ? "It is" : "They are"} still kept here and {deck.conflicts === 1 ? "is" : "are"} not part of the score.{" "}
              {deck.conflictsReported
                ? "The organizers have been sent a report and can see it on their scoring page."
                : deck.conflictsUnreportable
                  ? "A report couldn't be sent from this account, so show this screen to the organizers before removing anything."
                  : "A report goes to the organizers as soon as there is a connection."}{" "}
              Tell them if the score shown is wrong.
            </p>
            <button type="button" className={cn(deckButton, "self-start border-brand-gold text-brand-gold")} disabled={!deck.conflictsReported && !deck.conflictsUnreportable} onClick={() => void deck.dismissConflicts()}>
              Remove from this device
            </button>
          </div>
        )}
        {deck.problem && (
          <p role="alert" className="rounded-lg border border-brand-gold/60 bg-brand-gold/10 p-3 text-brand-gold">
            {problemText(deck.problem)}
          </p>
        )}
        {card && state && !deck.lost && !deck.failure && (
          <>
            {card.confirmed_at ? (
              <Confirmed card={card} state={state} back={back} />
            ) : state.status === "not_started" ? (
              deck.elsewhere !== null || deck.readOnly ? (
                <p className="rounded-xl border border-white/20 bg-white/5 p-4 text-white/80">The match hasn't started yet.</p>
              ) : (
                <Setup card={card} onStart={deck.act} />
              )
            ) : (
              <Play card={card} state={state} deck={deck} />
            )}
            <EventLog lines={describeLog(card, deck.stream, namesOf(card))} />
          </>
        )}
      </main>
    </div>
  )
}

function Message({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div role="alert" className="rounded-xl border border-white/20 bg-white/5 p-4">
      <h1 className="text-2xl font-bold">{title}</h1>
      <p className="mt-1 text-white/80">{children}</p>
    </div>
  )
}

function SyncChip({ sync, pending, onRetry }: { sync: Sync; pending: number; onRetry: () => void }) {
  if (sync === "saved") {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-brand-cyan">
        <CircleCheck aria-hidden className="size-4" /> Saved
      </span>
    )
  }
  if (sync === "sending") {
    return (
      <span role="status" className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-white/80">
        <LoaderCircle aria-hidden className="size-4 animate-spin" /> Saving…
      </span>
    )
  }
  return (
    <button type="button" onClick={onRetry} className="inline-flex min-h-12 shrink-0 items-center gap-1 rounded-lg border border-brand-gold px-3 text-sm font-semibold text-brand-gold outline-none focus-visible:ring-3 focus-visible:ring-brand-cyan">
      <CloudOff aria-hidden className="size-4" /> {pending} not saved. Retry
    </button>
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

/** Before the first point: the outcome of the lot. Who serves, who receives (doubles), and the ends. */
function Setup({ card, onStart }: { card: Scorecard; onStart: (event: { type: "start"; server: Player; receiver?: Player; a_end: End }) => void }) {
  const names = namesOf(card)
  const doubles = configOf(card).doubles
  const players = [...card.a.players, ...card.b.players]
  const [server, setServer] = useState<Player | "">("")
  const [receiver, setReceiver] = useState<Player | "">("")
  const [left, setLeft] = useState<Side | "">("")
  const receivers = server ? players.filter((player) => sideOf(player.slot as Player) !== sideOf(server)) : []
  const ready = server && left && (!doubles || receiver)

  return (
    <section aria-labelledby="setup-heading" className="flex flex-col gap-5 rounded-xl border border-white/20 bg-white/5 p-4">
      <div>
        <h1 id="setup-heading" className="text-2xl font-bold">
          Before the first point
        </h1>
        <p className="text-white/80">
          {names.a} v {names.b}. Best of {configOf(card).best_of} games.
        </p>
      </div>
      <Choice
        legend="Who serves first?"
        options={players.map((player) => ({ value: player.slot as Player, label: player.display_name }))}
        value={server}
        onChange={(player) => {
          setServer(player)
          setReceiver("")
        }}
      />
      {doubles && server && <Choice legend="Who receives first?" options={receivers.map((player) => ({ value: player.slot as Player, label: player.display_name }))} value={receiver} onChange={setReceiver} />}
      <Choice
        legend="Who starts at the left end, as you see the table?"
        options={[
          { value: "a" as Side, label: names.a },
          { value: "b" as Side, label: names.b },
        ]}
        value={left}
        onChange={setLeft}
      />
      <button
        type="button"
        className={cn(primaryButton, "self-start")}
        disabled={!ready}
        onClick={() => server && left && onStart({ type: "start", server, ...(doubles && receiver ? { receiver } : {}), a_end: left === "a" ? "left" : "right" })}
      >
        Start the match
      </button>
    </section>
  )
}

function Panel({ side, state, names, card, onPoint, live }: { side: Side; state: State; names: Names; card: Scorecard; onPoint: () => void; live: boolean }) {
  const index = side === "a" ? 0 : 1
  const serving = state.server !== null && sideOf(state.server) === side
  const receiving = state.receiver !== null && sideOf(state.receiver) === side
  const doubles = configOf(card).doubles
  return (
    <button
      type="button"
      disabled={!live}
      onClick={onPoint}
      aria-label={`Point for ${names[side]}. Now ${state.points[index]}, ${state.games_won[index]} games${serving ? ", serving" : ""}.`}
      className="flex min-h-[260px] flex-col items-center gap-2 p-3 text-center outline-none hover:bg-white/5 focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-brand-cyan active:bg-white/10 disabled:hover:bg-transparent"
    >
      <span className="text-lg leading-6 font-semibold break-words">{names[side]}</span>
      <span className="flex min-h-7 flex-wrap items-center justify-center gap-1">
        {serving && (
          <span className="rounded bg-brand-gold px-2 text-sm font-bold text-brand-navy">
            Serving{doubles && state.server ? `: ${names[state.server]}` : ""}
          </span>
        )}
        {doubles && receiving && state.receiver && <span className="rounded border border-white/40 px-2 text-sm">Receiving: {names[state.receiver]}</span>}
      </span>
      <span aria-hidden className="font-display text-[clamp(80px,24vw,144px)] leading-none font-bold tabular-nums">
        {state.points[index]}
      </span>
      <span className="text-sm text-white/80">
        Games <span className="font-display text-2xl font-bold text-white tabular-nums">{state.games_won[index]}</span>
      </span>
    </button>
  )
}

function Play({ card, state, deck }: { card: Scorecard; state: State; deck: ReturnType<typeof useDeck> }) {
  const names = namesOf(card)
  const config = configOf(card)
  const finished = state.status === "completed"
  // The panels follow the ends: whoever is at the left end of the table is on the left of the deck.
  // The umpire can turn the deck round (sitting on the other side of the table); a side moves with
  // everything that belongs to it: name, points, games, service and time-out.
  const [turned, setTurned] = useState(false)
  const order: Side[] = (state.a_end === "right") !== turned ? ["b", "a"] : ["a", "b"]
  const deciding = !finished && state.game_number === config.best_of
  const choosing = config.doubles && !finished && state.game_number > 1 && state.points[0] + state.points[1] === 0 && state.server
  const column = (side: Side) => (side === "a" ? 0 : 1)

  return (
    <>
      <section aria-label="Score" className="overflow-hidden rounded-xl border border-white/20 bg-white/5">
        <p className="border-b border-white/15 px-3 py-1.5 text-center text-sm font-semibold text-white/80">
          {finished ? "Match finished" : `Game ${state.game_number}${deciding ? " · deciding game" : ""} · first to ${gamesNeeded(config)} games`}
          {deciding && state.decider_changed && " · ends changed at 5"}
        </p>
        <div className="grid grid-cols-2 divide-x divide-white/20">
          {order.map((side) => (
            <Panel key={side} side={side} state={state} names={names} card={card} live={!finished} onPoint={() => deck.act({ type: "point", side })} />
          ))}
        </div>
        {state.games.length > 0 && (
          <ol aria-label="Finished games" className="grid grid-cols-2 border-t border-white/15 text-center tabular-nums">
            {state.games.map((game, number) => (
              <li key={number} className="col-span-2 grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-3 py-1 text-sm">
                <span className={cn("text-right text-lg", game[column(order[0])] > game[column(order[1])] && "font-bold")}>{game[column(order[0])]}</span>
                <span className="text-white/60">Game {number + 1}</span>
                <span className={cn("text-left text-lg", game[column(order[1])] > game[column(order[0])] && "font-bold")}>{game[column(order[1])]}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {choosing && state.server && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/20 bg-white/5 p-3">
          <p className="flex-1 font-semibold">Who serves first in this game?</p>
          {[state.server, partnerOf(state.server)].sort().map((player) => (
            <button key={player} type="button" aria-pressed={state.server === player} className={cn(deckButton, state.server === player && "border-brand-gold text-brand-gold")} onClick={() => deck.act({ type: "choose_server", player })}>
              {names[player]}
            </button>
          ))}
        </div>
      )}

      {finished ? (
        <Finish card={card} state={state} deck={deck} />
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <button type="button" className={deckButton} disabled={state.timeouts[column(order[0])]} onClick={() => deck.act({ type: "timeout", side: order[0] })}>
            Time-out
            <span className="sr-only"> for {names[order[0]]}</span>
          </button>
          <button type="button" className={deckButton} disabled={deck.undoable === 0} onClick={() => deck.act({ type: "undo" })}>
            <Undo2 aria-hidden className="size-5" /> Undo
          </button>
          <button type="button" className={deckButton} disabled={state.timeouts[column(order[1])]} onClick={() => deck.act({ type: "timeout", side: order[1] })}>
            Time-out
            <span className="sr-only"> for {names[order[1]]}</span>
          </button>
          <button type="button" className={cn(deckButton, "col-span-3")} aria-pressed={turned} onClick={() => setTurned(!turned)}>
            <ArrowLeftRight aria-hidden className="size-5" /> Swap the sides on screen
          </button>
          <p className="col-span-3 text-center text-sm text-white/70">
            Tap a side to give it the point. Each side has one time-out{state.timeouts.some(Boolean) ? `; used: ${order.filter((side) => state.timeouts[column(side)]).map((side) => names[side]).join(", ")}` : ""}.
          </p>
        </div>
      )}
    </>
  )
}

/** The explicit finish (REQ-002): the umpire reads the result back and confirms it. */
function Finish({ card, state, deck }: { card: Scorecard; state: State; deck: ReturnType<typeof useDeck> }) {
  const queryClient = useQueryClient()
  const names = namesOf(card)
  const confirm = useMutation({
    mutationFn: () => confirmScorecard(card),
    onSuccess: async () => {
      void queryClient.invalidateQueries({ queryKey: scoringKeys.mine })
      void queryClient.invalidateQueries({ queryKey: drawKeys.event(card.event_id) })
      void queryClient.invalidateQueries({ queryKey: drawKeys.standings(card.event_id) })
      void queryClient.invalidateQueries({ queryKey: drawKeys.match(card.match_id) })
      await deck.reload()
    },
  })
  const waiting = deck.pending > 0 || deck.sync !== "saved"
  return (
    <section aria-labelledby="finish-heading" className="flex flex-col gap-3 rounded-xl border border-brand-gold/60 bg-brand-gold/10 p-4">
      <h1 id="finish-heading" className="text-2xl font-bold">
        {state.winner ? names[state.winner] : "Nobody"} won {winnersScore(state)}
      </h1>
      <p className="text-white/80">Check the games above with both sides. Confirming makes the result official; after that only the organizers can correct it.</p>
      {confirm.isError && <p role="alert" className="text-brand-gold">{errorMessage(confirm.error)}</p>}
      {waiting && <p className="text-sm text-white/80">The last points are still being saved. You can confirm once they are.</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={primaryButton} disabled={waiting || confirm.isPending} onClick={() => confirm.mutate()}>
          {confirm.isPending ? "Confirming…" : "Confirm result"}
        </button>
        <button type="button" className={deckButton} disabled={confirm.isPending} onClick={() => deck.act({ type: "undo" })}>
          <Undo2 aria-hidden className="size-5" /> Undo the last point
        </button>
      </div>
    </section>
  )
}

function Confirmed({ card, state, back }: { card: Scorecard; state: State; back: string }) {
  const names = namesOf(card)
  return (
    <section aria-labelledby="confirmed-heading" className="flex flex-col gap-3 rounded-xl border border-white/20 bg-white/5 p-4">
      <h1 id="confirmed-heading" className="flex items-center gap-2 text-2xl font-bold">
        <CircleCheck aria-hidden className="size-6 text-brand-cyan" /> Result confirmed
      </h1>
      <p>
        {state.winner ? names[state.winner] : ""} won {winnersScore(state)} ({winnersGames(state)}).
      </p>
      <Link to={back} className={cn(primaryButton, "self-start")}>
        Back to the match
      </Link>
    </section>
  )
}

function EventLog({ lines }: { lines: LogLine[] }) {
  if (lines.length === 0) return null
  return (
    <section aria-labelledby="log-heading" className="flex min-h-0 flex-col gap-2">
      <h2 id="log-heading" className="text-lg font-semibold">
        Event log
      </h2>
      <ol className="flex max-h-64 flex-col overflow-y-auto rounded-xl border border-white/15 text-sm" tabIndex={0} aria-label="Events, newest first">
        {lines.map((line) => (
          <li key={line.sequence} className="flex gap-3 border-t border-white/10 px-3 py-1.5 first:border-t-0">
            <span className="w-8 shrink-0 text-right text-white/50 tabular-nums">{line.sequence}</span>
            <span>{line.text}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
