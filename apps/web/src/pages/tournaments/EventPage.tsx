import type { ReactNode } from "react"
import { Link, NavLink, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarDays, ChartColumn, LayoutGrid, Network, type LucideIcon } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { BracketView } from "@/components/tournaments/BracketView"
import { GroupsView } from "@/components/tournaments/GroupsView"
import { ScheduleView } from "@/components/tournaments/ScheduleView"
import { StandingsView } from "@/components/tournaments/StandingsView"
import { EventStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useMemberships } from "@/lib/clubs"
import { formatInstant } from "@/lib/dates"
import { drawKeys, getDraw, getStandings, type Draw, type Standings } from "@/lib/draws"
import { canManageTournament, eventSummary, eventTabPath, getTournament, tournamentKeys, type EventTab, type Tournament, type TournamentEvent } from "@/lib/tournaments"
import { cn } from "@/lib/utils"

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
            </div>
          </header>

          <nav aria-label="Event views" className="grid grid-cols-4 border-b">
            {TABS.map(({ tab: name, label, icon: Icon }) => (
              <NavLink
                key={name}
                to={eventTabPath(id, eventId, name)}
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
              <TabBody tab={tab} tournament={t} event={event} draw={published} standings={standings.data} standingsError={standings.error} />
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
  standings,
  standingsError,
}: {
  tab: EventTab
  tournament: Tournament
  event: TournamentEvent
  draw: Draw
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
    return <BracketView matches={knockout} matchPath={matchPath} timeZone={t.timezone} />
  }
  if (tab === "groups") {
    if (draw.groups.length === 0) {
      return (
        <NotApplicable to={path("brackets")} label="See the bracket">
          This event is a straight knockout: there are no groups, and a player who loses is out.
        </NotApplicable>
      )
    }
    return (
      <>
        {!!standingsError && <FormAlert>{errorMessage(standingsError, "We couldn't load who has qualified. The fixtures below are complete.")}</FormAlert>}
        <GroupsView draw={draw} standings={standings} matchPath={matchPath} timeZone={t.timezone} />
      </>
    )
  }
  if (tab === "schedule") return <ScheduleView draw={draw} matchPath={matchPath} timeZone={t.timezone} />

  if (standingsError) return <FormAlert>{errorMessage(standingsError, "We couldn't load the standings.")}</FormAlert>
  if (!standings) return <p className="text-muted-foreground">Loading standings…</p>
  return (
    <div className="flex flex-col gap-4">
      {draw.groups.length === 0 && (
        <NotApplicable to={path("brackets")} label="See the bracket">
          A knockout has no table. Only what the bracket has decided is listed here: the winner, the runner-up and who went out in each finished round. Nobody else is
          ranked.
        </NotApplicable>
      )}
      {draw.groups.length === 0 && standings.placements.length === 0 && <p className="text-muted-foreground">No round is finished yet.</p>}
      <StandingsView standings={standings} />
    </div>
  )
}
