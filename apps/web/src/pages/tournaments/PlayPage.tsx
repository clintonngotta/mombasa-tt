import { useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import { NotebookPen, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { NavCard } from "@/components/layout/NavCard"
import { TournamentCard } from "@/components/tournaments/TournamentCard"
import { errorMessage } from "@/lib/api"
import { listTournaments, tournamentKeys, type When } from "@/lib/tournaments"
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

      <NavCard to="/matches" icon={NotebookPen} title="Your match log" description="Matches you recorded yourself, with your progress" />
    </div>
  )
}
