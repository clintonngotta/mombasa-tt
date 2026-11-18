import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { NotebookPen, Search, Trophy } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { NavCard } from "@/components/layout/NavCard"
import { EntryStatusChip } from "@/components/tournaments/StatusChip"
import { TournamentCard } from "@/components/tournaments/TournamentCard"
import { errorMessage } from "@/lib/api"
import { formatDayRange } from "@/lib/dates"
import { entryKeys, entryTitle, isLive, listMyEntries } from "@/lib/entries"
import { listMyScorecards, SCORING_STATUS_LABEL, scoringKeys } from "@/lib/scoring"
import { isClosed, listTournaments, tournamentKeys, type When } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

const WHEN: { value: When; label: string }[] = [
  { value: "upcoming", label: "Upcoming" },
  { value: "past", label: "Past" },
]

/** Play tab: published tournaments (REQ-007), soonest first, and the way into the personal match log. */
export function PlayPage() {
  const [when, setWhen] = useState<When>("upcoming")
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")
  const tournaments = useQuery({ queryKey: tournamentKeys.list(when, term), queryFn: () => listTournaments(when, term) })
  const items = tournaments.data?.results ?? []

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <h1 className="text-[32px] leading-9 font-bold">Play</h1>
      <MyScorecards />
      <MyEntries />

      <section aria-labelledby="tournaments-heading" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="tournaments-heading" className="text-2xl font-bold">
            Tournaments
          </h2>
          <div role="group" aria-label="Which tournaments" className="flex rounded-lg border bg-card p-1">
            {WHEN.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={when === option.value}
                onClick={() => setWhen(option.value)}
                className={cn(
                  "h-12 rounded-md px-4 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  when === option.value && "bg-surface-selected text-brand-blue"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <form role="search" onSubmit={onSearch} className="flex gap-2">
          <label htmlFor="find-tournament" className="sr-only">
            Tournament, host or town
          </label>
          <Input id="find-tournament" type="search" placeholder="Tournament, host or town" value={input} onChange={(e) => setInput(e.target.value)} />
          <Button type="submit" size="icon" aria-label="Search">
            <Search aria-hidden className="size-5" />
          </Button>
        </form>

        <div aria-live="polite" className="flex flex-col gap-3">
          {tournaments.isPending && <p className="text-muted-foreground">Loading tournaments…</p>}
          {tournaments.isError && <FormAlert>{errorMessage(tournaments.error, "We couldn't load tournaments.")}</FormAlert>}
          {tournaments.isSuccess && items.length === 0 && (
            <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">
              {term ? `No ${when} tournament matches “${term}”.` : when === "upcoming" ? "No tournaments are coming up yet." : "No past tournaments yet."}
            </p>
          )}
          <ul className="flex flex-col gap-3">
            {items.map((tournament) => (
              <li key={tournament.id}>
                <TournamentCard tournament={tournament} />
              </li>
            ))}
          </ul>
          {tournaments.data && tournaments.data.count > items.length && (
            <p className="text-sm text-muted-foreground">
              Showing {items.length} of {tournaments.data.count}. Search to narrow the list.
            </p>
          )}
        </div>
      </section>

      <NavCard to="/rankings" icon={Trophy} title="Rankings" description="Singles and doubles ratings from tournament matches" />
      <NavCard to="/matches" icon={NotebookPen} title="Your match log" description="Matches you recorded yourself, with your progress" />
    </div>
  )
}

/** The caller's standing entries in tournaments that aren't over; nothing at all when there are none. */
function MyEntries() {
  const entries = useQuery({ queryKey: entryKeys.mine, queryFn: listMyEntries })
  const current = (entries.data?.results ?? []).filter((entry) => isLive(entry) && !isClosed(entry.tournament) && !isClosed(entry.event))
  if (current.length === 0) return null
  return (
    <section aria-labelledby="my-entries-heading" className="flex flex-col gap-3">
      <h2 id="my-entries-heading" className="text-2xl font-bold">
        Your entries
      </h2>
      <ul className="flex flex-col gap-2">
        {current.map((entry) => (
          <li key={entry.id}>
            <Link
              to={`/tournaments/${entry.tournament.id}/events/${entry.event.id}/entries`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <span className="flex min-w-0 flex-col">
                <span className="font-semibold break-words">
                  {entry.event.name} · {entry.tournament.name}
                </span>
                <span className="text-sm text-muted-foreground">
                  {formatDayRange(entry.tournament.starts_on, entry.tournament.ends_on)}
                  {entry.players.length > 1 && ` · ${entryTitle(entry)}`}
                </span>
              </span>
              <EntryStatusChip status={entry.status} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
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
