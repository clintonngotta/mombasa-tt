import type { ReactNode } from "react"
import { Link, NavLink, useParams, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarDays, ChartColumn, FileDown, ImageDown, LayoutGrid, Network, type LucideIcon } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { SearchBox } from "@/components/forms/SearchBox"
import { Segmented } from "@/components/forms/Segmented"
import { SearchSelect } from "@/components/forms/SelectField"
import { BracketView } from "@/components/tournaments/BracketView"
import { GroupsView } from "@/components/tournaments/GroupsView"
import { ScheduleView } from "@/components/tournaments/ScheduleView"
import { StandingsView } from "@/components/tournaments/StandingsView"
import { EventStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatInstant } from "@/lib/dates"
import { drawKeys, drawSheetUrl, filterDraw, getDraw, getStandings, type Draw, type DrawFilters, type Standings } from "@/lib/draws"
import { entryText, matchesSearch } from "@/lib/search"
import { canManageTournament, eventSummary, eventTabPath, getTournament, tournamentKeys, type EventTab, type Tournament, type TournamentEvent } from "@/lib/tournaments"
import { cn } from "@/lib/utils"
import { useLiveTournament } from "@/lib/live"

const TABS: { tab: EventTab; label: string; icon: LucideIcon }[] = [
  { tab: "brackets", label: "Brackets", icon: Network },
  { tab: "groups", label: "Groups", icon: LayoutGrid },
  { tab: "schedule", label: "Schedule", icon: CalendarDays },
  { tab: "standings", label: "Standings", icon: ChartColumn },
]

/**
 * One event's Brackets, Groups, Schedule and Standings (REQ-010). All four tabs are always there; a tab
 * that doesn't apply to the event's format says why and where to look instead.
 */
export function EventPage({ tab }: { tab: EventTab }) {
  const { id = "", eventId = "" } = useParams()
  useLiveTournament(id)
  const { results: memberships } = useMemberships()
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const t = tournament.data
  const event = t?.events.find((candidate) => candidate.id === eventId)
  const draw = useQuery({
    queryKey: drawKeys.event(eventId),
    queryFn: () => getDraw(id, eventId),
    enabled: tournament.isSuccess,
    refetchInterval: tab === "brackets" && event?.status === "in_progress" ? 5000 : false,
  })
  const published = draw.data?.published ?? null
  const standings = useQuery({ queryKey: drawKeys.standings(eventId), queryFn: () => getStandings(id, eventId), enabled: !!published })
  const staff = !!t && canManageTournament(memberships, t)
  const missing = (tournament.error instanceof ApiError && tournament.error.status === 404) || (!!t && !event)
  const [params, setParams] = useSearchParams()
  const filters = readFilters(params)
  const setFilter = (name: "q" | "group" | "stage", value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (value) next.set(name, value)
        else next.delete(name)
        return next
      },
      { replace: true }
    )

  return (
    <div className="flex max-w-[1200px] flex-col gap-5">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? "Tournament"}</BackLink>
      {tournament.isPending && <p className="text-muted-foreground">Loading event…</p>}
      {missing && <FormAlert>This event doesn't exist or hasn't been published.</FormAlert>}
      {tournament.isError && !missing && <FormAlert>{errorMessage(tournament.error, "We couldn't load this event.")}</FormAlert>}
      {t && event && (
        <>
          <header className="flex flex-col gap-2">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h1 className="min-w-0 text-[32px] leading-9 font-bold break-words">{event.name}</h1>
              <EventStatusChip status={event.status} />
            </div>
            <p className="text-muted-foreground">{eventSummary(event)}</p>
            {event.paused_at && (
              <FormAlert>This event is paused while the organizers decide about a corrected result. Matches already on a table carry on; no new match is sent out until it is settled.</FormAlert>
            )}
            <div className="flex flex-wrap gap-2">
              <Link to={`/tournaments/${id}/events/${eventId}/entries`} className={buttonVariants({ variant: "outline" })}>
                Entries
              </Link>
              {staff && (
                <Link to={`/tournaments/${id}/events/${eventId}/draw`} className={buttonVariants({ variant: "outline" })}>
                  Draw desk
                </Link>
              )}
              {published && (
                <>
                  <a href={drawSheetUrl(id, eventId, "pdf")} className={buttonVariants({ variant: "outline" })}>
                    <FileDown aria-hidden /> Draw (PDF)
                  </a>
                  <a href={drawSheetUrl(id, eventId, "png")} download className={buttonVariants({ variant: "outline" })}>
                    <ImageDown aria-hidden /> Draw image
                  </a>
                </>
              )}
            </div>
          </header>

          <nav aria-label="Event views" className="grid grid-cols-4 border-b">
            {TABS.map(({ tab: name, label, icon: Icon }) => (
              <NavLink
                key={name}
                to={{ pathname: eventTabPath(id, eventId, name), search: params.toString() ? `?${params}` : "" }}
                replace
                className={({ isActive }) =>
                  cn(
                    "flex min-h-14 flex-col items-center justify-center gap-0.5 border-b-[3px] border-transparent px-1 py-1.5 text-sm font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:flex-row sm:gap-2 sm:text-base",
                    isActive && "border-brand-blue text-brand-blue"
                  )
                }
              >
                <Icon aria-hidden className="size-5" />
                {label}
              </NavLink>
            ))}
          </nav>

          {draw.isPending && <p className="text-muted-foreground">Loading draw…</p>}
          {draw.isError && <FormAlert>{errorMessage(draw.error, "We couldn't load the draw.")}</FormAlert>}
          {draw.data && !published && <NotDrawn event={event} tab={tab} />}
          {published && (
            <section aria-label={TABS.find((candidate) => candidate.tab === tab)?.label} className="flex flex-col gap-4">
              {published.stale && <FormAlert>The entries have changed since this draw was published. The organizers will publish a new one.</FormAlert>}
              <FilterBar tab={tab} draw={published} filters={filters} onChange={setFilter} />
              <TabBody tab={tab} tournament={t} event={event} draw={published} filters={filters} standings={standings.data} standingsError={standings.error} />
              <p className="text-sm text-muted-foreground">
                Draw version {published.version}
                {published.published_at && `, published ${formatInstant(published.published_at, t.timezone)}`}. Rules {published.rules_version}, draw number {published.rng_seed}.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  )
}

function readFilters(params: URLSearchParams): DrawFilters {
  const group = Number(params.get("group"))
  const stage = params.get("stage")
  return {
    search: (params.get("q") ?? "").slice(0, 100),
    group: Number.isInteger(group) && group > 0 ? group : null,
    stage: stage === "group" || stage === "knockout" ? stage : "",
  }
}

const STAGES: { value: "" | "group" | "knockout"; label: string }[] = [
  { value: "", label: "All stages" },
  { value: "group", label: "Groups" },
  { value: "knockout", label: "Knockout" },
]

/** Search by player or team on every tab; pick a group where there are several, and a stage on the schedule. */
function FilterBar({ tab, draw, filters, onChange }: { tab: EventTab; draw: Draw; filters: DrawFilters; onChange: (name: "q" | "group" | "stage", value: string) => void }) {
  const groups = draw.groups.length > 1 && tab !== "brackets"
  const stages = tab === "schedule" && draw.groups.length > 0 && draw.matches.some((match) => match.stage === "knockout")
  return (
    <div className="flex flex-wrap items-end gap-3">
      <SearchBox label="Search players and teams" placeholder="Name" value={filters.search} onChange={(value) => onChange("q", value)} className="w-full sm:w-72" />
      {groups && (
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-semibold">Group</span>
          <SearchSelect
            aria-label="Group"
            value={filters.group ? String(filters.group) : ""}
            onChange={(value) => onChange("group", value)}
            options={[{ value: "", label: "All groups" }, ...draw.groups.map((group) => ({ value: String(group.number), label: group.name }))]}
          />
        </div>
      )}
      {stages && <Segmented label="Stage" options={STAGES} value={filters.stage} onChange={(value) => onChange("stage", value)} />}
    </div>
  )
}

const NOTHING_FITS = "Nothing fits these filters."

/** What a tab will hold for this event's format once the draw is published, or why it will hold nothing. */
const BEFORE_DRAW: Record<EventTab, Record<TournamentEvent["format"], string>> = {
  brackets: {
    knockout: "The bracket appears here once the draw is published.",
    groups_knockout: "The knockout bracket appears here once the draw is published. The groups are played first and their qualifiers fill it.",
    round_robin: "This event is a round robin: everybody plays everybody and the table decides the places, so it will have no bracket.",
  },
  groups: {
    knockout: "This event is a straight knockout, so it will have no groups.",
    groups_knockout: "The groups and their fixtures appear here once the draw is published.",
    round_robin: "The fixtures appear here once the draw is published.",
  },
  schedule: {
    knockout: "The matches appear here once the draw is published.",
    groups_knockout: "The matches appear here once the draw is published.",
    round_robin: "The matches appear here once the draw is published.",
  },
  standings: {
    knockout: "A knockout has no table. Once it is played, the winner, the runner-up and who went out in each round are listed here.",
    groups_knockout: "The group tables appear here once the draw is published.",
    round_robin: "The table appears here once the draw is published.",
  },
}

function NotDrawn({ event, tab }: { event: TournamentEvent; tab: EventTab }) {
  return (
    <p className="text-muted-foreground">
      {event.status === "cancelled" ? "This event was cancelled before a draw was published." : `The draw hasn't been published yet. ${BEFORE_DRAW[tab][event.format]}`}
    </p>
  )
}

/** Why a tab has nothing to show for this format, and where the event's matches are instead. */
function NotApplicable({ children, to, label }: { children: ReactNode; to: string; label: string }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border bg-card p-4">
      <p>{children}</p>
      <Link to={to} className={buttonVariants({ variant: "outline" })}>
        {label}
      </Link>
    </div>
  )
}

function TabBody({
  tab,
  tournament: t,
  event,
  draw,
  filters,
  standings,
  standingsError,
}: {
  tab: EventTab
  tournament: Tournament
  event: TournamentEvent
  draw: Draw
  filters: DrawFilters
  standings?: Standings
  standingsError: unknown
}) {
  const path = (name: EventTab) => eventTabPath(t.id, event.id, name)
  const matchPath = (matchId: string) => `/tournaments/${t.id}/events/${event.id}/matches/${matchId}`
  const knockout = draw.matches.filter((match) => match.stage === "knockout")

  if (tab === "brackets") {
    if (knockout.length === 0) {
      return (
        <NotApplicable to={path("groups")} label="See the fixtures">
          This event is a round robin: everybody plays everybody and the table decides the places, so there is no bracket.
        </NotApplicable>
      )
    }
    return <BracketView matches={knockout} search={filters.search} matchPath={matchPath} timeZone={t.timezone} />
  }
  if (tab === "groups") {
    if (draw.groups.length === 0) {
      return (
        <NotApplicable to={path("brackets")} label="See the bracket">
          This event is a straight knockout: there are no groups, and a player who loses is out.
        </NotApplicable>
      )
    }
    const shown = filterDraw(draw, { ...filters, stage: "group" })
    // While searching, a group shows only if someone in it, or one of its matches, fits.
    const groups = filters.search
      ? { ...shown, groups: shown.groups.filter((group) => shown.places.some((place) => place.group === group.number) || shown.matches.some((match) => match.group === group.number)) }
      : shown
    return (
      <>
        {!!standingsError && <FormAlert>{errorMessage(standingsError, "We couldn't load who has qualified. The fixtures below are complete.")}</FormAlert>}
        {groups.groups.length === 0 ? <p className="text-muted-foreground">{NOTHING_FITS}</p> : <GroupsView draw={groups} single={draw.groups.length === 1} standings={standings} matchPath={matchPath} timeZone={t.timezone} />}
      </>
    )
  }
  if (tab === "schedule") return <ScheduleView draw={filterDraw(draw, filters)} groups={draw.groups} matchPath={matchPath} timeZone={t.timezone} />

  if (standingsError) return <FormAlert>{errorMessage(standingsError, "We couldn't load the standings.")}</FormAlert>
  if (!standings) return <p className="text-muted-foreground">Loading standings…</p>
  const fits = (entry: { title: string; players?: { display_name: string }[] }) => matchesSearch(filters.search, entryText(entry))
  const narrowed: Standings = {
    ...standings,
    groups: standings.groups
      .filter((group) => filters.group === null || group.number === filters.group)
      .map((group) => ({ ...group, rows: group.rows.filter((row) => fits(row.entry)) }))
      .filter((group) => group.rows.length > 0),
    placements: filters.group === null ? standings.placements.map((placement) => ({ ...placement, entries: placement.entries.filter(fits) })).filter((placement) => placement.entries.length > 0) : [],
  }
  const filtering = !!filters.search || filters.group !== null
  return (
    <div className="flex flex-col gap-4">
      {draw.groups.length === 0 && (
        <NotApplicable to={path("brackets")} label="See the bracket">
          A knockout has no table. Only what the bracket has decided is listed here: the winner, the runner-up and who went out in each finished round. Nobody else is
          ranked.
        </NotApplicable>
      )}
      {draw.groups.length === 0 && standings.placements.length === 0 && <p className="text-muted-foreground">No round is finished yet.</p>}
      {filtering && narrowed.groups.length === 0 && narrowed.placements.length === 0 ? <p className="text-muted-foreground">{NOTHING_FITS}</p> : <StandingsView standings={narrowed} single={standings.groups.length === 1} />}
    </div>
  )
}
