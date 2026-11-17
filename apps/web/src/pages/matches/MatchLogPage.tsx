import type { ReactNode } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { ChevronRight, Lock, Plus } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { LabelPill, MatchSides, ResultBadge, SetScores } from "@/components/matches/MatchSides"
import { errorMessage } from "@/lib/api"
import {
  RESULT_LABEL,
  formatPlayedOn,
  getMatchStats,
  listMatches,
  matchKeys,
  type MatchResult,
  type MatchStats,
} from "@/lib/matchlog"
import { cn } from "@/lib/utils"

export function MatchLogPage() {
  const [params, setParams] = useSearchParams()
  const label = params.get("label") ?? undefined

  const stats = useQuery({ queryKey: matchKeys.stats(label), queryFn: () => getMatchStats(label) })
  // Unfiltered stats provide the label chips even while a filter is applied.
  const allStats = useQuery({ queryKey: matchKeys.stats(), queryFn: () => getMatchStats() })
  const matches = useInfiniteQuery({
    queryKey: matchKeys.list(label),
    queryFn: ({ pageParam }) => listMatches(label, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  })

  const setLabel = (next?: string) => setParams(next ? { label: next } : {}, { replace: true })
  const items = matches.data?.pages.flatMap((p) => p.results) ?? []
  const labels = allStats.data?.by_label ?? []

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">My match log</h1>
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Lock aria-hidden className="size-4" /> Private to you. Doesn't affect ratings or standings.
          </p>
        </div>
        <Link to="/matches/new" className={buttonVariants()}>
          <Plus aria-hidden className="size-5" /> Record a match
        </Link>
      </div>

      {labels.length > 1 && (
        <div role="group" aria-label="Filter by label" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
          <FilterChip active={!label} onClick={() => setLabel()}>
            All
          </FilterChip>
          {labels.map((l) => (
            <FilterChip key={l.label} active={label?.toLowerCase() === l.label.toLowerCase()} onClick={() => setLabel(l.label)}>
              {l.label} <span className="text-muted-foreground">{l.played}</span>
            </FilterChip>
          ))}
        </div>
      )}

      {stats.data && stats.data.played > 0 && <StatsPanel stats={stats.data} />}

      <section aria-labelledby="matches-heading" className="flex flex-col gap-3">
        <h2 id="matches-heading" className="sr-only">
          Matches
        </h2>
        {matches.isPending && <p className="text-muted-foreground">Loading your matches…</p>}
        {matches.isError && <FormAlert>{errorMessage(matches.error, "We couldn't load your matches.")}</FormAlert>}
        {matches.isSuccess && items.length === 0 && (
          <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-card p-6">
            <p className="font-semibold">{label ? `No “${label}” matches yet.` : "No matches recorded yet."}</p>
            <p className="text-muted-foreground">
              Record friendlies, practice games or tournaments played elsewhere, set by set, to see how you're
              progressing.
            </p>
          </div>
        )}
        <ul className="flex flex-col gap-3">
          {items.map((match) => (
            <li key={match.id}>
              <Link
                to={`/matches/${match.id}`}
                className="flex flex-col gap-3 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <LabelPill label={match.label} />
                  <ResultBadge result={match.result} />
                  <span className="text-muted-foreground">{formatPlayedOn(match.played_on)}</span>
                  <ChevronRight aria-hidden className="ml-auto size-5 text-muted-foreground" />
                </div>
                <MatchSides match={match} />
                <SetScores match={match} />
              </Link>
            </li>
          ))}
        </ul>
        {matches.hasNextPage && (
          <Button variant="outline" disabled={matches.isFetchingNextPage} onClick={() => matches.fetchNextPage()}>
            {matches.isFetchingNextPage ? "Loading…" : "Show more"}
          </Button>
        )}
      </section>
    </div>
  )
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex h-12 shrink-0 items-center gap-1.5 rounded-full border px-4 font-semibold whitespace-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        active ? "border-brand-blue bg-surface-selected text-brand-blue" : "bg-card"
      )}
    >
      {children}
    </button>
  )
}

const FORM_STYLE: Record<MatchResult, string> = {
  win: "bg-success text-white",
  loss: "bg-destructive text-white",
  draw: "bg-muted text-muted-foreground",
}
const FORM_LETTER: Record<MatchResult, string> = { win: "W", loss: "L", draw: "D" }

function StatsPanel({ stats }: { stats: MatchStats }) {
  const tiles = [
    ["Played", stats.played],
    ["Won", stats.won],
    ["Lost", stats.lost],
    ["Win rate", stats.win_rate === null ? "–" : `${Math.round(stats.win_rate * 100)}%`],
  ] as const

  return (
    <section aria-label="Progress" className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <dl className="grid grid-cols-4 gap-2">
        {tiles.map(([name, value]) => (
          <div key={name} className="flex flex-col gap-0.5">
            <dt className="text-sm text-muted-foreground">{name}</dt>
            <dd className="font-display text-3xl font-bold tabular">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Recent form <span className="sr-only">(newest first)</span>
          <span aria-hidden> · newest first</span>
        </p>
        <ol className="flex flex-wrap gap-1.5">
          {stats.recent_form.map((r, i) => (
            <li
              key={i}
              aria-label={RESULT_LABEL[r]}
              className={cn("flex size-8 items-center justify-center rounded-md text-sm font-bold", FORM_STYLE[r])}
            >
              {FORM_LETTER[r]}
            </li>
          ))}
        </ol>
      </div>
      <p className="text-sm text-muted-foreground tabular">
        Sets won {stats.games_won} · lost {stats.games_lost}
      </p>
    </section>
  )
}
