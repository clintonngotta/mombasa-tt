import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarRange, CupSoda, Medal, NotebookPen, Timer, Trophy, Warehouse } from "lucide-react"
import { NavCard } from "@/components/layout/NavCard"
import { MyEntries } from "@/components/tournaments/TournamentLists"
import { listMyScorecards, SCORING_STATUS_LABEL, scoringKeys } from "@/lib/scoring"

/** Play tab: the matches you umpire, your entries, and every way to get a game. Tournaments have their own tab. */
export function PlayPage() {
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <h1 className="text-[32px] leading-9 font-bold">Play</h1>
      <MyScorecards />
      <MyEntries />

      <nav aria-label="Ways to play" className="flex flex-col gap-3">
        <NavCard to="/tournaments" icon={Medal} title="Tournaments" description="Find one, enter its events and follow the scores" />
        <NavCard to="/facilities" icon={Warehouse} title="Find a place to play" description="Halls with tables near you: hours, open now and what a visit includes" />
        <NavCard to="/play/soda" icon={CupSoda} title="Soda games" description="Challenge a friend to a friendly match: unrated, no booking" />
        <NavCard to="/quick-score" icon={Timer} title="Quick Score" description="Score a casual game on this phone: no rating, no booking" />
        <NavCard to="/matches" icon={NotebookPen} title="Your match log" description="Matches you recorded yourself, with your progress" />
        <NavCard to="/events" icon={CalendarRange} title="Events calendar" description="Tournaments across the country, here and elsewhere, with live links" />
        <NavCard to="/rankings" icon={Trophy} title="Rankings" description="Singles and doubles ratings from tournament matches" />
      </nav>
    </div>
  )
}

/** Matches the player is assigned to umpire and hasn't confirmed. Shown only when there are some. */
function MyScorecards() {
  const cards = useQuery({ queryKey: scoringKeys.mine, queryFn: listMyScorecards, staleTime: 30_000 })
  const items = cards.data?.results ?? []
  if (items.length === 0) return null
  return (
    <section aria-labelledby="scorecards-heading" className="flex flex-col gap-3 rounded-xl border border-brand-blue/30 bg-surface-selected p-4">
      <h2 id="scorecards-heading" className="text-2xl font-bold">
        Matches you umpire
      </h2>
      <ul className="flex flex-col gap-2">
        {items.map((card) => (
          <li key={card.id}>
            <Link to={`/score/${card.id}`} className="flex min-h-12 flex-col gap-0.5 rounded-lg border bg-card px-3 py-2 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50">
              <span className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 font-semibold">
                <span className="min-w-0 break-words">{card.a.title}</span>
                <span className="text-sm font-normal text-muted-foreground">v</span>
                <span className="min-w-0 text-right break-words">{card.b.title}</span>
              </span>
              <span className="text-sm text-muted-foreground">
                {[card.tournament_name, card.event_name, card.label, card.table].filter(Boolean).join(" · ")} · {SCORING_STATUS_LABEL[card.status]}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
