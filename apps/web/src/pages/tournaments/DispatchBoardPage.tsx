import { useEffect, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Ban, CircleCheck, CircleDot, Clock, Hourglass, Megaphone, TriangleAlert, UserCheck } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { Toggle } from "@/components/forms/Toggle"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { drawKeys, getMatch } from "@/lib/draws"
import { UmpireControl } from "@/components/tournaments/UmpireControl"
import { UmpiresPanel } from "@/components/tournaments/UmpiresPanel"
import {
  blockTable,
  callAgain,
  controlKeys,
  dispatchMatch,
  getBoard,
  getDesk,
  getMatchDayLog,
  moveMatch,
  recallMatch,
  reportSide,
  reservationKeys,
  runAutoDispatch,
  setAutoDispatch,
  TABLE_BLOCK_REASONS,
  unblockTable,
  type Board,
  type BoardTable,
  type DeskEntry,
  type QueuedMatch,
  type TableBlockReason,
} from "@/lib/reservations"
import { changeEntry } from "@/lib/entries"
import { cn } from "@/lib/utils"
import { scoringKeys } from "@/lib/scoring"
import { getTournament, tournamentKeys } from "@/lib/tournaments"
import { useLiveTournament } from "@/lib/live"

const LOOK_EVERY = 15_000

const STATE = {
  ready: { label: "Ready", icon: CircleCheck, className: "text-success" },
  waiting: { label: "Waiting", icon: Hourglass, className: "text-muted-foreground" },
  blocked: { label: "Held up", icon: TriangleAlert, className: "text-warning" },
} as const

/** How each table state reads on the board (REQ-043). */
const TABLE_STATE: Record<BoardTable["state"], { label: string; icon: typeof CircleCheck; className: string }> = {
  free: { label: "Free", icon: CircleCheck, className: "text-success" },
  called: { label: "Called", icon: Megaphone, className: "text-warning" },
  warming_up: { label: "Warming up", icon: UserCheck, className: "text-brand-blue" },
  in_play: { label: "In play", icon: CircleDot, className: "text-brand-blue" },
  blocked: { label: "Blocked", icon: Ban, className: "text-destructive" },
}

const VIEWS = [
  { value: "tables", label: "Tables" },
  { value: "umpires", label: "Umpires" },
  { value: "desk", label: "Check-in desk" },
  { value: "log", label: "Log" },
] as const
type View = (typeof VIEWS)[number]["value"]

const matchPath = (tournamentId: string, row: { event_id: string; match_id: string }) => `/tournaments/${tournamentId}/events/${row.event_id}/matches/${row.match_id}`

/** The two sides left and right (REQ-002). */
function Sides({ a, b }: { a: string; b: string }) {
  return (
    <p className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-semibold">
      <span className="min-w-0 break-words">{a}</span>
      <span className="text-sm font-normal text-muted-foreground">v</span>
      <span className="min-w-0 text-right break-words">{b}</span>
    </p>
  )
}

/**
 * The match-day control centre for a tournament's competition staff (REQ-043, built on the REQ-014
 * dispatch board): every table and its state, calls and who has reported, players flagged after the
 * grace period, the queue in its fixed order, the check-in desk and the match-day log. A match shown
 * next to a free table is a suggestion; Send asks the server, which checks everything again.
 */
export function DispatchBoardPage() {
  const { id = "" } = useParams()
  useLiveTournament(id)
  const [params, setParams] = useSearchParams()
  const view: View = VIEWS.some((v) => v.value === params.get("view")) ? (params.get("view") as View) : "tables"
  const queryClient = useQueryClient()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const board = useQuery({ queryKey: reservationKeys.board(id), queryFn: () => getBoard(id), refetchInterval: LOOK_EVERY, staleTime: 0 })
  const refused = board.error instanceof ApiError && (board.error.status === 403 || board.error.status === 404)
  const keep = (fresh: Board) => {
    queryClient.setQueryData(reservationKeys.board(id), fresh)
    void queryClient.invalidateQueries({ queryKey: scoringKeys.overview(id) })
  }
  const auto = useMutation({ mutationFn: (enabled: boolean) => setAutoDispatch(id, enabled), onSuccess: keep })
  const look = useMutation({ mutationFn: () => runAutoDispatch(id), onSuccess: keep })
  const automatic = board.data?.auto_dispatch ?? false
  const lookNow = look.mutate
  const looking = look.isPending

  // While the board is open and automatic dispatch is on, it looks again regularly: a rest that has
  // just ended frees a match without any result arriving to trigger it.
  useEffect(() => {
    if (!automatic) return
    if (looking) return // one look at a time: a slow one isn't followed by another on its heels
    const timer = setInterval(() => {
      if (!document.hidden) lookNow()
    }, LOOK_EVERY)
    return () => clearInterval(timer)
  }, [automatic, looking, lookNow])

  const t = tournament.data
  const data = board.data
  const byId = new Map(data?.queue.map((row) => [row.match_id, row]))

  return (
    <div className="flex max-w-[1100px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}/dashboard`}>{t?.name ?? "Tournament"}</BackLink>
      <header className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Control centre</h1>
        <p className="text-muted-foreground">Every table and its match, who has been called and has reported, what goes out next, the check-in desk and a log of every action.</p>
      </header>
      <div role="tablist" aria-label="Control centre" className="flex gap-1 overflow-x-auto border-b">
        {VIEWS.map((v) => (
          <button
            key={v.value}
            role="tab"
            type="button"
            aria-selected={view === v.value}
            onClick={() => setParams(v.value === "tables" ? {} : { view: v.value }, { replace: true })}
            className={cn(
              "-mb-px min-h-12 shrink-0 border-b-2 px-4 font-semibold whitespace-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              view === v.value ? "border-brand-blue text-brand-blue" : "border-transparent text-muted-foreground"
            )}
          >
            {v.label}
          </button>
        ))}
      </div>
      {view === "umpires" && data && <UmpiresPanel tournamentId={id} tables={data.tables} />}
      {view === "desk" && t && <CheckInDesk tournamentId={id} timeZone={t.timezone} />}
      {view === "log" && t && <MatchDayLog tournamentId={id} timeZone={t.timezone} />}
      {(board.isPending || (tournament.isPending && !board.isError)) && <p className="text-muted-foreground">Loading…</p>}
      {tournament.isError && !refused && <FormAlert>{errorMessage(tournament.error, "We couldn't load this tournament.")}</FormAlert>}
      {refused && <AccessLost />}
      {board.isError && !refused && <FormAlert>{errorMessage(board.error, "We couldn't load the tables.")}</FormAlert>}
      {view === "tables" && data && t && (
        <>
          <Summary tables={data.tables} />
          <NoShows tournamentId={id} tables={data.tables} />
          {!data.in_play && (
            <FormAlert>
              This tournament isn't under way, so no match can go to a table. Start the tournament and each event on{" "}
              <Link to={`/tournaments/${id}`} className="font-semibold underline underline-offset-4">
                the tournament's page
              </Link>
              .
            </FormAlert>
          )}
          <Toggle
            checked={automatic}
            onChange={(enabled) => {
              if (!auto.isPending) auto.mutate(enabled)
            }}
            label="Send matches out automatically"
            description="When a table is free, the first match in the queue that can be played goes to it without anybody pressing Send. Check-in and rest are never set aside. While this page is open it looks again every few seconds; otherwise it looks whenever a result comes in."
          />
          {auto.isPending && <p className="text-sm text-muted-foreground">Saving…</p>}
          {auto.isError && <FormAlert>{errorMessage(auto.error)}</FormAlert>}
          {automatic && look.isError && <FormAlert>Automatic sending couldn't look just now: {errorMessage(look.error)} It tries again shortly; you can still send matches yourself.</FormAlert>}

          <section aria-labelledby="board-tables" className="flex flex-col gap-3">
            <h2 id="board-tables" className="text-2xl font-bold">
              Tables
            </h2>
            {data.tables.length === 0 ? (
              <p className="text-muted-foreground">This tournament's venue has no tables in use. Add them under Club, Venues.</p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {data.tables.map((table) => (
                  <TableCard
                    key={table.id}
                    tournamentId={id}
                    table={table}
                    freeTables={data.tables.filter((other) => other.state === "free")}
                    next={table.suggested_match_id ? byId.get(table.suggested_match_id) : undefined}
                    timeZone={t.timezone}
                  />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="board-queue" className="flex flex-col gap-3">
            <h2 id="board-queue" className="text-2xl font-bold">
              Queue
            </h2>
            <p className="text-sm text-muted-foreground">
              In order: planned start first, then the match that has waited longest.
              {data.to_come > 0 && ` ${data.to_come} more ${data.to_come === 1 ? "match waits" : "matches wait"} for an earlier result and will join the queue.`}
            </p>
            {data.queue.length === 0 ? (
              <p className="text-muted-foreground">No match is waiting for a table.</p>
            ) : (
              <ol className="flex flex-col gap-3">
                {data.queue.map((row) => (
                  <QueueRow key={row.match_id} tournamentId={id} row={row} timeZone={t.timezone} />
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function TableCard({ tournamentId, table, freeTables, next, timeZone }: { tournamentId: string; table: BoardTable; freeTables: BoardTable[]; next?: QueuedMatch; timeZone: string }) {
  const queryClient = useQueryClient()
  const [sentFor, setSentFor] = useState("")
  const send = useMutation({
    mutationFn: (row: QueuedMatch) => dispatchMatch(tournamentId, row.event_id, row.match_id, table.id, [], ""),
    onMutate: (row) => setSentFor(row.match_id),
    // Sent or refused, the board has changed since it was drawn: read it again.
    onSettled: (_data, _error, row) => {
      void queryClient.invalidateQueries({ queryKey: reservationKeys.board(tournamentId) })
      void queryClient.invalidateQueries({ queryKey: drawKeys.match(row.match_id) })
      void queryClient.invalidateQueries({ queryKey: scoringKeys.overview(tournamentId) })
    },
  })
  const state = TABLE_STATE[table.state]
  const Icon = state.icon
  const playing = table.playing
  return (
    <li className={cn("flex flex-col gap-2 rounded-xl border bg-card p-4", table.call?.no_show.length ? "border-warning" : "")}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-bold">{table.label}</h3>
        <span className={`flex items-center gap-1 text-sm font-semibold ${state.className}`}>
          <Icon aria-hidden className="size-5" /> {state.label}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">{table.table_umpire ? `Table umpire: ${table.table_umpire.name}` : "No table umpire"}</p>
      {table.block && (
        <>
          <p className="text-sm">
            {table.block.reason_label}
            {table.block.note && `: ${table.block.note}`}. Since {formatInstant(table.block.since, timeZone)}
            {table.block.by && `, by ${table.block.by}`}.
          </p>
          <Unblock tournamentId={tournamentId} table={table} />
        </>
      )}
      {playing && <OnTable tournamentId={tournamentId} table={table} freeTables={freeTables} timeZone={timeZone} />}
      {table.next_up && (
        <div className="flex flex-col gap-1 rounded-lg border border-brand-blue/40 bg-brand-blue/5 p-3">
          <p className="text-sm font-semibold text-brand-blue">
            Next here, once the result is confirmed: {table.next_up.event_name}
          </p>
          <Sides a={table.next_up.a} b={table.next_up.b} />
          <p className="text-xs text-muted-foreground">A recommendation: nothing is sent until the table is free.</p>
        </div>
      )}
      {!table.free && !playing && !table.block && <p className="text-sm">Taken by {table.held_by}.</p>}
      {table.state === "free" && next && (
        <>
          <p className="text-sm font-semibold text-muted-foreground">
            Next: {next.event_name} · {next.label}
          </p>
          <Sides a={next.a} b={next.b} />
          <Button className="self-start" disabled={send.isPending} onClick={() => send.mutate(next)}>
            {send.isPending ? "Sending…" : `Send to ${table.label}`}
          </Button>
        </>
      )}
      {send.isError && sentFor === next?.match_id && <FormAlert>Not sent: {errorMessage(send.error)}</FormAlert>}
      {table.state === "free" && !next && <p className="text-sm text-muted-foreground">{table.idle_reason}</p>}
      {table.state === "free" && <Block tournamentId={tournamentId} table={table} />}
    </li>
  )
}

/** Counts of tables in each state, at a glance. */
function Summary({ tables }: { tables: BoardTable[] }) {
  return (
    <ul className="flex flex-wrap gap-2" aria-label="Tables by state">
      {(Object.keys(TABLE_STATE) as BoardTable["state"][]).map((key) => {
        const shown = TABLE_STATE[key]
        const n = tables.filter((table) => table.state === key).length
        return (
          <li key={key} className="flex items-center gap-1.5 rounded-full border bg-card px-3 py-1.5 text-sm font-semibold">
            <shown.icon aria-hidden className={`size-4 ${shown.className}`} /> {shown.label} <span className="tabular-nums">{n}</span>
          </li>
        )
      })}
    </ul>
  )
}

/** Called players who haven't reported within the grace period: only the referee awards a walkover. */
function NoShows({ tournamentId, tables }: { tournamentId: string; tables: BoardTable[] }) {
  const flagged = tables.filter((table) => table.playing && table.call && table.call.no_show.length > 0)
  if (flagged.length === 0) return null
  return (
    <section aria-labelledby="no-shows" className="flex flex-col gap-2 rounded-xl border border-warning bg-card p-4">
      <h2 id="no-shows" className="flex items-center gap-2 text-lg font-bold">
        <TriangleAlert aria-hidden className="size-5 text-warning" /> Not at the table after the grace period
      </h2>
      <ul className="flex flex-col gap-1">
        {flagged.map((table) => {
          const playing = table.playing!
          const names = table.call!.no_show.map((side) => (side === "a" ? playing.a : playing.b)).join(" and ")
          return (
            <li key={table.id}>
              {table.label}: {names}.{" "}
              <Link to={matchPath(tournamentId, playing)} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
                Open the match
              </Link>
            </li>
          )
        })}
      </ul>
      <p className="text-sm text-muted-foreground">Call them again, or ask the referee: only the referee can award a walkover.</p>
    </section>
  )
}

/** The match on a table: who has reported, its call, umpire and score, and the actions staff take. */
function OnTable({ tournamentId, table, freeTables, timeZone }: { tournamentId: string; table: BoardTable; freeTables: BoardTable[]; timeZone: string }) {
  const queryClient = useQueryClient()
  const playing = table.playing!
  const call = table.call
  const [mode, setMode] = useState<"" | "move" | "recall">("")
  const [target, setTarget] = useState("")
  const [reason, setReason] = useState("")
  const fresh = (board: Board) => {
    queryClient.setQueryData(reservationKeys.board(tournamentId), board)
    void queryClient.invalidateQueries({ queryKey: controlKeys.log(tournamentId) })
    void queryClient.invalidateQueries({ queryKey: drawKeys.match(playing.match_id) })
  }
  const report = useMutation({ mutationFn: ({ side, undo }: { side: "a" | "b"; undo: boolean }) => reportSide(tournamentId, playing.event_id, playing.match_id, side, undo), onSuccess: fresh })
  const again = useMutation({ mutationFn: () => callAgain(tournamentId, playing.event_id, playing.match_id), onSuccess: fresh })
  const move = useMutation({
    mutationFn: () => moveMatch(tournamentId, playing.event_id, playing.match_id, target, reason.trim()),
    onSuccess: (board) => {
      fresh(board)
      setMode("")
      setReason("")
    },
  })
  const recall = useMutation({
    mutationFn: () => recallMatch(tournamentId, playing.event_id, playing.match_id, reason.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: reservationKeys.board(tournamentId) })
      void queryClient.invalidateQueries({ queryKey: controlKeys.log(tournamentId) })
      setMode("")
      setReason("")
    },
  })
  const failed = report.error ?? again.error
  const inPlay = table.state === "in_play"
  return (
    <>
      <p className="text-sm font-semibold text-muted-foreground">{playing.event_name}</p>
      <Sides a={playing.a} b={playing.b} />
      {table.score && (
        <p className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-display text-xl tabular-nums" aria-label="Live score">
          <span>
            {table.score.games_won[0]} <span className="text-base text-muted-foreground">({table.score.points[0]})</span>
          </span>
          <span className="text-sm font-normal text-muted-foreground">{table.score.rubber ? `Rubber ${table.score.rubber}` : "games"}</span>
          <span className="text-right">
            <span className="text-base text-muted-foreground">({table.score.points[1]})</span> {table.score.games_won[1]}
          </span>
        </p>
      )}
      {table.score?.rubbers_won && (
        <p className="text-sm text-muted-foreground">
          Rubbers {table.score.rubbers_won[0]}–{table.score.rubbers_won[1]}
        </p>
      )}
      <BoardUmpire tournamentId={tournamentId} table={table} />
      {call && !inPlay && (
        <>
          <p className="text-sm text-muted-foreground">
            Called {formatInstant(call.called_at, timeZone)}
            {call.calls > 1 && `, ${call.calls} times`}. Grace until {formatInstant(call.grace_until, timeZone)}.
          </p>
          <div role="group" aria-label="At the table" className="grid grid-cols-2 gap-2">
            {(["a", "b"] as const).map((side) => {
              const at = side === "a" ? call.a_reported_at : call.b_reported_at
              const late = call.no_show.includes(side)
              return (
                <button
                  key={side}
                  type="button"
                  aria-pressed={!!at}
                  disabled={report.isPending}
                  onClick={() => report.mutate({ side, undo: !!at })}
                  className={cn(
                    "flex min-h-12 min-w-0 items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    side === "b" && "flex-row-reverse text-right",
                    at ? "border-success text-success" : late ? "border-warning text-warning" : "text-muted-foreground"
                  )}
                >
                  {at ? <UserCheck aria-hidden className="size-5 shrink-0" /> : late ? <TriangleAlert aria-hidden className="size-5 shrink-0" /> : <Hourglass aria-hidden className="size-5 shrink-0" />}
                  <span className="min-w-0 break-words">{at ? `${side === "a" ? playing.a : playing.b} is here` : `${side === "a" ? playing.a : playing.b}: not yet`}</span>
                </button>
              )
            })}
          </div>
        </>
      )}
      {failed && <FormAlert>{errorMessage(failed)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Link to={matchPath(tournamentId, playing)} className={buttonVariants({ variant: "outline" })}>
          Open the match
        </Link>
        {!inPlay && (
          <Button variant="outline" disabled={again.isPending} onClick={() => again.mutate()}>
            {again.isPending ? "Calling…" : "Call again"}
          </Button>
        )}
        <Button variant="ghost" onClick={() => setMode(mode === "move" ? "" : "move")} aria-expanded={mode === "move"}>
          Move
        </Button>
        <Button variant="ghost" onClick={() => setMode(mode === "recall" ? "" : "recall")} aria-expanded={mode === "recall"}>
          Take off
        </Button>
      </div>
      {mode !== "" && (
        <form
          className="flex flex-col gap-3 rounded-lg border p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (mode === "move") move.mutate()
            else recall.mutate()
          }}
        >
          {mode === "move" &&
            (freeTables.length === 0 ? (
              <p className="text-sm text-muted-foreground">No table is free to move to.</p>
            ) : (
              <SelectField label="Move to" value={target} onChange={setTarget} options={[{ value: "", label: "Choose a table" }, ...freeTables.map((free) => ({ value: free.id, label: free.label }))]} />
            ))}
          <Field label={mode === "move" ? "Why move it?" : "Why take it off?"} required maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} hint="Kept in the match-day log." />
          {(move.error ?? recall.error) && <FormAlert>{errorMessage(move.error ?? recall.error)}</FormAlert>}
          <Button type="submit" className="self-start" disabled={!reason.trim() || (mode === "move" && !target) || move.isPending || recall.isPending}>
            {mode === "move" ? "Move the match" : "Take it off the table"}
          </Button>
        </form>
      )}
    </>
  )
}

/** The umpire of the match on a table, and choosing or changing them without leaving the board. */
function BoardUmpire({ tournamentId, table }: { tournamentId: string; table: BoardTable }) {
  const playing = table.playing!
  const [open, setOpen] = useState(false)
  const match = useQuery({ queryKey: drawKeys.match(playing.match_id), queryFn: () => getMatch(tournamentId, playing.event_id, playing.match_id), enabled: open })
  return (
    <div className="flex flex-col gap-2">
      <p className="flex flex-wrap items-center gap-x-2 text-sm">
        {table.umpire ? `Umpire: ${table.umpire}.` : "No umpire yet."}
        <button type="button" className="min-h-10 font-semibold text-brand-blue underline-offset-4 hover:underline" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Close" : table.umpire ? "Change" : "Choose one"}
        </button>
      </p>
      {open && match.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {open && match.isError && <FormAlert>{errorMessage(match.error)}</FormAlert>}
      {open && match.data && !match.data.scoring && <p className="text-sm text-muted-foreground">A tie's umpires are chosen rubber by rubber on the match page.</p>}
      {open && match.data?.scoring && <UmpireControl scoring={match.data.scoring} ids={{ tournamentId, eventId: playing.event_id, matchId: playing.match_id }} what="this match" />}
    </div>
  )
}

function Block({ tournamentId, table }: { tournamentId: string; table: BoardTable }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState<TableBlockReason>("out_of_service")
  const [note, setNote] = useState("")
  const block = useMutation({
    mutationFn: () => blockTable(tournamentId, table.id, reason, note.trim()),
    onSuccess: (board) => {
      queryClient.setQueryData(reservationKeys.board(tournamentId), board)
      void queryClient.invalidateQueries({ queryKey: controlKeys.log(tournamentId) })
      setOpen(false)
      setNote("")
    },
  })
  if (!open)
    return (
      <Button variant="ghost" className="self-start" onClick={() => setOpen(true)}>
        Block this table
      </Button>
    )
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border p-3"
      onSubmit={(e) => {
        e.preventDefault()
        block.mutate()
      }}
    >
      <SelectField label="Why" value={reason} onChange={(value) => setReason(value as TableBlockReason)} options={TABLE_BLOCK_REASONS} />
      <Field label="Note" optional maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} />
      {block.isError && <FormAlert>{errorMessage(block.error)}</FormAlert>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={block.isPending}>
          Block {table.label}
        </Button>
        <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function Unblock({ tournamentId, table }: { tournamentId: string; table: BoardTable }) {
  const queryClient = useQueryClient()
  const unblock = useMutation({
    mutationFn: () => unblockTable(tournamentId, table.id),
    onSuccess: (board) => {
      queryClient.setQueryData(reservationKeys.board(tournamentId), board)
      void queryClient.invalidateQueries({ queryKey: controlKeys.log(tournamentId) })
    },
  })
  return (
    <>
      <Button variant="outline" className="self-start" disabled={unblock.isPending} onClick={() => unblock.mutate()}>
        Put back in use
      </Button>
      {unblock.isError && <FormAlert>{errorMessage(unblock.error)}</FormAlert>}
    </>
  )
}

/** The check-in desk: who still has to arrive, and checking them in or undoing it. */
function CheckInDesk({ tournamentId, timeZone }: { tournamentId: string; timeZone: string }) {
  const [search, setSearch] = useState("")
  const desk = useQuery({ queryKey: controlKeys.desk(tournamentId), queryFn: () => getDesk(tournamentId) })
  if (desk.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (desk.isError) return <FormAlert>{errorMessage(desk.error, "We couldn't load the check-in desk.")}</FormAlert>
  const wanted = search.trim().toLowerCase()
  const rows = desk.data.filter((row) => !wanted || row.title.toLowerCase().includes(wanted) || row.event_name.toLowerCase().includes(wanted))
  const waiting = desk.data.filter((row) => !row.checked_in_at).length
  return (
    <section aria-labelledby="desk-heading" className="flex flex-col gap-3">
      <h2 id="desk-heading" className="text-2xl font-bold">
        Check-in desk
      </h2>
      <p className="text-muted-foreground">
        {waiting === 0 ? "Everybody has checked in." : `${waiting} still to check in, of ${desk.data.length}.`} Players can also check themselves in on the tournament's days.
      </p>
      <Field label="Find a player, team or event" value={search} onChange={(e) => setSearch(e.target.value)} />
      {rows.length === 0 ? (
        <p className="text-muted-foreground">Nobody matches.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <DeskRow key={row.id} tournamentId={tournamentId} row={row} timeZone={timeZone} />
          ))}
        </ul>
      )}
    </section>
  )
}

function DeskRow({ tournamentId, row, timeZone }: { tournamentId: string; row: DeskEntry; timeZone: string }) {
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: () => changeEntry(tournamentId, row.event_id, row.id, row.checked_in_at ? "undo-check-in" : "check-in"),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: controlKeys.desk(tournamentId) })
      void queryClient.invalidateQueries({ queryKey: controlKeys.log(tournamentId) })
      void queryClient.invalidateQueries({ queryKey: reservationKeys.board(tournamentId) })
    },
  })
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-3">
      <div className="flex min-w-0 flex-col">
        <span className="font-semibold break-words">{row.title}</span>
        <span className="text-sm text-muted-foreground">
          {row.event_name}
          {row.checked_in_at && ` · checked in ${formatInstant(row.checked_in_at, timeZone)}${row.checked_in_by ? ` by ${row.checked_in_by}` : ""}`}
        </span>
        {change.isError && <span className="text-sm text-destructive">{errorMessage(change.error)}</span>}
      </div>
      <Button variant={row.checked_in_at ? "ghost" : "default"} disabled={change.isPending} onClick={() => change.mutate()}>
        {row.checked_in_at ? "Undo check-in" : "Check in"}
      </Button>
    </li>
  )
}

/** Every match-day action, newest first, with who did it and why. */
function MatchDayLog({ tournamentId, timeZone }: { tournamentId: string; timeZone: string }) {
  const log = useQuery({ queryKey: controlKeys.log(tournamentId), queryFn: () => getMatchDayLog(tournamentId) })
  if (log.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (log.isError) return <FormAlert>{errorMessage(log.error, "We couldn't load the log.")}</FormAlert>
  return (
    <section aria-labelledby="log-heading" className="flex flex-col gap-3">
      <h2 id="log-heading" className="text-2xl font-bold">
        Match-day log
      </h2>
      <p className="text-muted-foreground">Calls, moves, players reporting, check-ins, umpires, blocked tables and results, newest first. The latest 200.</p>
      {log.data.length === 0 ? (
        <p className="text-muted-foreground">Nothing has happened yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {log.data.map((entry) => (
            <li key={entry.id} className="flex flex-col gap-0.5 rounded-xl border bg-card p-3">
              <span className="text-sm text-muted-foreground">
                {formatInstant(entry.at, timeZone)} · {entry.actor || "Automatic"}
              </span>
              <span>
                <span className="font-semibold">{entry.action_label}</span>: {entry.summary}
              </span>
              {entry.reason && <span className="text-sm">Reason: {entry.reason}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function QueueRow({ tournamentId, row, timeZone }: { tournamentId: string; row: QueuedMatch; timeZone: string }) {
  const state = STATE[row.state]
  const Icon = state.icon
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-muted-foreground">
          {row.position !== null && <span className="mr-2 font-display text-base text-foreground tabular-nums">{row.position}</span>}
          {row.event_name} · {row.label}
        </p>
        <span className={`flex items-center gap-1 text-sm font-semibold ${state.className}`}>
          <Icon aria-hidden className="size-5" /> {state.label}
          {row.state === "ready" && row.suggested_table && `: ${row.suggested_table}`}
        </span>
      </div>
      <Sides a={row.a} b={row.b} />
      <p className="flex items-center gap-1 text-sm text-muted-foreground">
        <Clock aria-hidden className="size-4 shrink-0" />
        <span>
          {row.planned_at && `Planned for ${formatInstant(row.planned_at, timeZone)}. `}Waiting since {formatInstant(row.ready_since, timeZone)}.
        </span>
      </p>
      {row.reasons.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {row.reasons.map((reason) => (
            <li key={reason.code + reason.message}>
              {reason.message}
              {reason.until && ` Free to play from ${formatInstant(reason.until, timeZone)}.`}
            </li>
          ))}
        </ul>
      )}
      <Link to={matchPath(tournamentId, row)} className={buttonVariants({ variant: "outline", className: "self-start" })}>
        Open the match
      </Link>
    </li>
  )
}
