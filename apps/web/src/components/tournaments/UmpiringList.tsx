import { useState } from "react"
import { Link } from "react-router-dom"
import { useInfiniteQuery } from "@tanstack/react-query"
import { Clock } from "lucide-react"
import { Button } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { UmpireControl } from "@/components/tournaments/UmpireControl"
import { errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { getUmpiring, reservationKeys, type UmpiringFilter, type UmpiringRow } from "@/lib/reservations"
import type { ScoringSummary } from "@/lib/scoring"
import { cn } from "@/lib/utils"

const FILTERS: { value: UmpiringFilter; label: string }[] = [
  { value: "unassigned", label: "No umpire yet" },
  { value: "assigned", label: "With an umpire" },
  { value: "all", label: "All" },
]

/**
 * Who umpires each match still to be played (TASK-153): the matches given to an umpire, and those still
 * waiting for one, soonest first. Staff give or change the umpire on each row.
 */
export function UmpiringList({ tournamentId, timeZone }: { tournamentId: string; timeZone: string }) {
  const [which, setWhich] = useState<UmpiringFilter>("unassigned")
  const rows = useInfiniteQuery({
    queryKey: reservationKeys.umpiringIn(tournamentId, which),
    queryFn: ({ pageParam }) => getUmpiring(tournamentId, which, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  })
  const totals = rows.data?.pages[0]?.totals
  const found = rows.data?.pages.flatMap((page) => page.results) ?? []

  return (
    <section aria-labelledby="umpiring-heading" className="flex flex-col gap-3">
      <h2 id="umpiring-heading" className="text-2xl font-bold">
        Who umpires each match
      </h2>
      <p className="text-sm text-muted-foreground">Every match still to be played, soonest first. A tie is umpired rubber by rubber, once both lineups are in.</p>
      <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
        {FILTERS.map((filter) => {
          const count = totals ? (filter.value === "all" ? totals.assigned + totals.unassigned : totals[filter.value]) : null
          return (
            <button
              key={filter.value}
              type="button"
              aria-pressed={which === filter.value}
              onClick={() => setWhich(filter.value)}
              className={cn(
                "min-h-11 rounded-full border px-4 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                which === filter.value ? "border-brand-blue bg-brand-blue text-white" : "text-muted-foreground"
              )}
            >
              {filter.label}
              {count !== null && ` (${count})`}
            </button>
          )
        })}
      </div>
      {rows.isPending && <p className="text-muted-foreground">Loading…</p>}
      {rows.isError && <FormAlert>{errorMessage(rows.error, "We couldn't load the matches.")}</FormAlert>}
      {rows.isSuccess && found.length === 0 && (
        <p className="text-muted-foreground">{which === "unassigned" ? "Every match still to be played has an umpire." : which === "assigned" ? "No match has an umpire yet." : "No match is waiting to be played."}</p>
      )}
      {found.length > 0 && (
        <ul className="flex flex-col gap-3">
          {found.map((row) => (
            <Row key={row.rubber_id ?? row.match_id} tournamentId={tournamentId} row={row} timeZone={timeZone} />
          ))}
        </ul>
      )}
      {rows.hasNextPage && (
        <Button variant="outline" className="self-start" disabled={rows.isFetchingNextPage} onClick={() => void rows.fetchNextPage()}>
          {rows.isFetchingNextPage ? "Loading…" : "Show more"}
        </Button>
      )}
    </section>
  )
}

function Row({ tournamentId, row, timeZone }: { tournamentId: string; row: UmpiringRow; timeZone: string }) {
  const scoring: ScoringSummary = {
    scorecard_id: null,
    status: row.status as ScoringSummary["status"],
    umpire_name: row.umpire_name,
    can_score: false,
    can_assign: true,
    incidents: [],
    live: null,
  }
  const where = row.table ? `On ${row.table}` : row.held_table ? `Waits for ${row.held_table}` : row.planned_table ? `Planned for ${row.planned_table}` : ""
  return (
    <li className="flex flex-col gap-2 rounded-xl border bg-card p-4">
      <p className="text-sm font-semibold text-muted-foreground">
        {row.event_name} · {row.label}
      </p>
      <p className="font-semibold">
        <Link to={`/tournaments/${tournamentId}/events/${row.event_id}/matches/${row.match_id}`} className="underline-offset-4 hover:underline">
          {row.a} v {row.b}
        </Link>
      </p>
      {(row.scheduled_at || where) && (
        <p className="flex items-center gap-1 text-sm text-muted-foreground">
          <Clock aria-hidden className="size-4 shrink-0" />
          <span>{[row.scheduled_at ? formatInstant(row.scheduled_at, timeZone) : "", where].filter(Boolean).join(" · ")}</span>
        </p>
      )}
      <UmpireControl
        scoring={scoring}
        ids={{ tournamentId, eventId: row.event_id, matchId: row.match_id }}
        rubberId={row.rubber_id ?? undefined}
        what={row.rubber_position ? `rubber ${row.rubber_position}` : "this match"}
      />
    </li>
  )
}
