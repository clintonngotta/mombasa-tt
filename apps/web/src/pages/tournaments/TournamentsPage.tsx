import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarRange, LayoutDashboard, Plus, Search } from "lucide-react"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { SelectField } from "@/components/forms/SelectField"
import { LiveNow, MyEntries } from "@/components/tournaments/TournamentLists"
import { TournamentCard } from "@/components/tournaments/TournamentCard"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { SCOPE_OPTIONS, listTournaments, tournamentKeys, type TournamentScope, type When } from "@/lib/tournaments"

const WHEN: { value: When; label: string }[] = [
  { value: "upcoming", label: "Upcoming" },
  { value: "past", label: "Past" },
]

/**
 * The Tournaments tab (REQ-007): what is being played now, the player's own entries, and every published
 * tournament to open, enter and follow. Whoever runs competitions in the active club also starts a new
 * one from here. Open to anyone, signed in or not, like the tournament pages themselves.
 */
export function TournamentsPage() {
  const [when, setWhen] = useState<When>("upcoming")
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")
  const [scope, setScope] = useState<TournamentScope | "">("")
  const { active } = useActiveMembership()
  const organizer = !!active && !active.managedOnly && can(active, "competitions.manage")
  const tournaments = useQuery({ queryKey: tournamentKeys.list(when, term, scope), queryFn: () => listTournaments(when, term, scope) })
  const items = tournaments.data?.results ?? []
  const narrowed = !!term || !!scope

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  function onClear() {
    setInput("")
    setTerm("")
    setScope("")
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">Tournaments</h1>
          <p className="text-muted-foreground">Open one to enter its events, see the draw and follow the scores.</p>
        </div>
        {organizer && (
          <div className="flex flex-wrap gap-2">
            <Link to="/club/tournaments" className={buttonVariants({ variant: "outline" })}>
              <LayoutDashboard aria-hidden className="size-5" /> Manage yours
            </Link>
            <Link to="/club/tournaments/new" className={buttonVariants()}>
              <Plus aria-hidden className="size-5" /> New tournament
            </Link>
          </div>
        )}
      </div>

      <LiveNow />
      <MyEntries />

      <section aria-labelledby="all-tournaments-heading" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="all-tournaments-heading" className="text-2xl font-bold">
            Find a tournament
          </h2>
          <Segmented label="Which tournaments" options={WHEN} value={when} onChange={setWhen} />
        </div>

        <form role="search" onSubmit={onSearch} className="flex gap-2">
          <label htmlFor="find-tournament" className="sr-only">
            Tournament, host or town
          </label>
          <Input id="find-tournament" type="search" maxLength={120} placeholder="Tournament, host or town" value={input} onChange={(e) => setInput(e.target.value)} />
          <Button type="submit" size="icon" aria-label="Search">
            <Search aria-hidden className="size-5" />
          </Button>
        </form>
        <SelectField label="Level" value={scope} onChange={(value) => setScope(value as TournamentScope | "")} options={[{ value: "", label: "Any level" }, ...SCOPE_OPTIONS]} />

        <div aria-live="polite" className="flex flex-col gap-3">
          {tournaments.isPending && <p className="text-muted-foreground">Loading tournaments…</p>}
          {tournaments.isError && <FormAlert>{errorMessage(tournaments.error, "We couldn't load tournaments.")}</FormAlert>}
          {tournaments.isSuccess && items.length === 0 && (
            <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed bg-card p-6 text-muted-foreground">
              <p>{narrowed ? `No ${when} tournament matches your search.` : when === "upcoming" ? "No tournaments are coming up yet." : "No past tournaments yet."}</p>
              {narrowed ? (
                <Button type="button" variant="outline" onClick={onClear}>
                  Clear search
                </Button>
              ) : (
                <Link to="/events" className="font-semibold text-brand-blue underline">
                  See the events calendar
                </Link>
              )}
            </div>
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

      <Link to="/events" className="flex items-center gap-2 font-semibold text-brand-blue">
        <CalendarRange aria-hidden className="size-5" /> Events calendar: tournaments elsewhere too, with live links
      </Link>
    </div>
  )
}
