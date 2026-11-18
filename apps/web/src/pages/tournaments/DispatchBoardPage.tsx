import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CircleCheck, CircleDot, Clock, Hourglass, TriangleAlert } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { Toggle } from "@/components/forms/Toggle"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ApiError, errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { drawKeys } from "@/lib/draws"
import { dispatchMatch, getBoard, reservationKeys, runAutoDispatch, setAutoDispatch, type Board, type BoardTable, type QueuedMatch } from "@/lib/reservations"
import { scoringKeys } from "@/lib/scoring"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

const LOOK_EVERY = 15_000

const STATE = {
  ready: { label: "Ready", icon: CircleCheck, className: "text-success" },
  waiting: { label: "Waiting", icon: Hourglass, className: "text-muted-foreground" },
  blocked: { label: "Held up", icon: TriangleAlert, className: "text-warning" },
} as const

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
 * The dispatch board for a tournament's competition staff (REQ-014): every table, the queue of matches
 * in its fixed order, and what keeps each held-up match from a table. A match shown next to a free
 * table is a suggestion; Send asks the server, which checks everything again and may refuse.
 */
export function DispatchBoardPage() {
  const { id = "" } = useParams()
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

  // While the board is open and automatic dispatch is on, it looks again regularly: a rest that has
  // just ended frees a match without any result arriving to trigger it.
  useEffect(() => {
    if (!automatic) return
    const timer = setInterval(() => lookNow(), LOOK_EVERY)
    return () => clearInterval(timer)
  }, [automatic, lookNow])

  const t = tournament.data
  const data = board.data
  const byId = new Map(data?.queue.map((row) => [row.match_id, row]))

  return (
    <div className="flex max-w-[900px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      <header className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Tables</h1>
        <p className="text-muted-foreground">Which match is on which table, which goes out next, and what the others are waiting for.</p>
      </header>
      {(board.isPending || (tournament.isPending && !board.isError)) && <p className="text-muted-foreground">Loading…</p>}
      {tournament.isError && !refused && <FormAlert>{errorMessage(tournament.error, "We couldn't load this tournament.")}</FormAlert>}
      {refused && <AccessLost />}
      {board.isError && !refused && <FormAlert>{errorMessage(board.error, "We couldn't load the tables.")}</FormAlert>}
      {data && t && (
        <>
          {!data.in_play && <FormAlert>This tournament isn't under way, so no match can go to a table.</FormAlert>}
          <Toggle
            checked={automatic}
            onChange={(enabled) => auto.mutate(enabled)}
            label="Send matches out automatically"
            description="When a table is free, the first match in the queue that can be played goes to it without anybody pressing Send. Check-in and rest are never set aside. While this page is open it looks again every few seconds; otherwise it looks whenever a result comes in."
          />
          {auto.isError && <FormAlert>{errorMessage(auto.error)}</FormAlert>}

          <section aria-labelledby="board-tables" className="flex flex-col gap-3">
            <h2 id="board-tables" className="text-2xl font-bold">
              Tables
            </h2>
            {data.tables.length === 0 ? (
              <p className="text-muted-foreground">This tournament's venue has no tables in use. Add them under Club, Venues.</p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2">
                {data.tables.map((table) => (
                  <TableCard key={table.id} tournamentId={id} table={table} next={table.suggested_match_id ? byId.get(table.suggested_match_id) : undefined} timeZone={t.timezone} />
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

function TableCard({ tournamentId, table, next, timeZone }: { tournamentId: string; table: BoardTable; next?: QueuedMatch; timeZone: string }) {
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
  const playing = table.playing
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-bold">{table.label}</h3>
        {table.free ? (
          <span className="flex items-center gap-1 text-sm font-semibold text-success">
            <CircleCheck aria-hidden className="size-5" /> Free
          </span>
        ) : (
          <span className="flex items-center gap-1 text-sm font-semibold text-brand-blue">
            <CircleDot aria-hidden className="size-5" /> In use
          </span>
        )}
      </div>
      {playing && (
        <>
          <p className="text-sm font-semibold text-muted-foreground">{playing.event_name}</p>
          <Sides a={playing.a} b={playing.b} />
          <p className="text-sm">Since {formatInstant(playing.since, timeZone)}. Held until the result is official.</p>
          <Link to={matchPath(tournamentId, playing)} className={buttonVariants({ variant: "outline", className: "self-start" })}>
            Open the match
          </Link>
        </>
      )}
      {!table.free && !playing && <p className="text-sm">Taken by {table.held_by}.</p>}
      {table.free && next && (
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
      {send.isError && sentFor && <FormAlert>Not sent: {errorMessage(send.error)}</FormAlert>}
      {table.free && !next && <p className="text-sm text-muted-foreground">{table.idle_reason}</p>}
    </li>
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
