import { Link } from "react-router-dom"
import { useInfiniteQuery } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { formatInstant } from "@/lib/dates"
import { listMyScorecards, SCORING_STATUS_LABEL, scoringKeys, type MyScorecard, type UmpiringState } from "@/lib/scoring"

/** Every match the signed-in person is given to umpire: those still to score, soonest first, and the
 * results they confirmed. Staff assign them; each assignment is also sent as an alert. */
export function UmpiringPage() {
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <BackLink to="/play">Play</BackLink>
        <h1 className="text-[32px] leading-9 font-bold">Your umpiring</h1>
        <p className="text-muted-foreground">Matches staff gave you to umpire. You're told each time one is added or taken off you.</p>
      </div>
      <Cards state="open" title="To umpire" empty="No matches to umpire right now." />
      <Cards state="done" title="Umpired" empty="Results you confirm show up here." />
    </div>
  )
}

function Cards({ state, title, empty }: { state: UmpiringState; title: string; empty: string }) {
  const cards = useInfiniteQuery({
    queryKey: scoringKeys.mineIn(state),
    queryFn: ({ pageParam }) => listMyScorecards(state, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
    staleTime: 30_000,
  })
  const items = cards.data?.pages.flatMap((page) => page.results) ?? []
  const id = `umpiring-${state}`
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-2xl font-bold">
        {title}
      </h2>
      {cards.isPending ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : cards.isError ? (
        <p role="alert" className="text-destructive">
          {errorMessage(cards.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((card) => (
            <li key={card.id}>
              <Card card={card} />
            </li>
          ))}
        </ul>
      )}
      {cards.hasNextPage && (
        <Button variant="outline" className="self-start" disabled={cards.isFetchingNextPage} onClick={() => cards.fetchNextPage()}>
          {cards.isFetchingNextPage ? "Loading…" : "Show more"}
        </Button>
      )}
    </section>
  )
}

function Card({ card }: { card: MyScorecard }) {
  const done = card.status === "confirmed"
  // An open sheet opens the deck; a confirmed one, the match with its official result.
  const to = done ? `/tournaments/${card.tournament_id}/events/${card.event_id}/matches/${card.match_id}` : `/score/${card.id}`
  const table = card.table || card.planned_table
  const when = done ? (card.confirmed_at ? `Confirmed ${formatInstant(card.confirmed_at, card.timezone)}` : "") : card.scheduled_at ? formatInstant(card.scheduled_at, card.timezone) : "Time not set yet"
  const games = card.state.games.map(([a, b]) => `${a}–${b}`).join(", ")
  return (
    <Link to={to} className="flex min-h-12 flex-col gap-1 rounded-lg border bg-card px-3 py-2 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50">
      <span className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-semibold">
        <span className="min-w-0 break-words">{card.a.title}</span>
        <span className="text-sm font-normal text-muted-foreground">v</span>
        <span className="min-w-0 text-right break-words">{card.b.title}</span>
      </span>
      <span className="text-sm text-muted-foreground">{[card.tournament_name, card.event_name, card.label].filter(Boolean).join(" · ")}</span>
      <span className="flex flex-wrap gap-x-3 text-sm">
        <span className="font-medium">{when}</span>
        {!done && <span>{table ? (card.table ? `On ${table}` : `Planned for ${table}`) : "Table not set yet"}</span>}
        {done && games && <span className="tabular-nums">{games}</span>}
        {!done && <span className="text-muted-foreground">{SCORING_STATUS_LABEL[card.status]}</span>}
      </span>
    </Link>
  )
}
