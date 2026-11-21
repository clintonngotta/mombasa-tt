import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CircleCheck, CircleAlert } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { EventStatusChip, TournamentStatusChip } from "@/components/tournaments/StatusChip"
import { ApiError, errorMessage } from "@/lib/api"
import { useLiveTournament } from "@/lib/live"
import { cn } from "@/lib/utils"
import {
  eventTabPath,
  firstTab,
  getTournament,
  getTournamentDashboard,
  tournamentKeys,
  type EventDashboard,
  type Tournament,
  type TournamentDashboard,
} from "@/lib/tournaments"

const DRAW_LABEL: Record<EventDashboard["draw"], string> = { none: "No draw yet", preview: "Draw being prepared", published: "Draw published" }
const CEREMONY_LABEL: Record<TournamentDashboard["ceremony"], string> = { none: "Not set up", draft: "Draft", published: "Published" }

/** Every desk the dashboard links, so the top row and the event cards name and route each one the same way. */
const DESK = {
  schedule: { path: "schedule-plan", label: "Schedule" },
  tables: { path: "dispatch", label: "Control centre" },
  scoring: { path: "scoring", label: "Scoring" },
  corrections: { path: "corrections", label: "Corrections" },
  ceremony: { path: "ceremony", label: "Ceremony" },
} as const
type Desk = keyof typeof DESK
const deskPath = (tournamentId: string, desk: Desk) => `/tournaments/${tournamentId}/${DESK[desk].path}`

/** "1 entry waits" or "3 entries wait": the count with the right form of its words. */
const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/**
 * The organizer's dashboard of one tournament (REQ-020, TASK-035): where every event stands in counts,
 * and what needs competition staff next. Counts only: names stay on the entry desk and the draw desk.
 */
export function TournamentDashboardPage() {
  const { id = "" } = useParams()
  useLiveTournament(id)
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  // Entries arrive without a live message, so look again now and then as well.
  const dashboard = useQuery({ queryKey: tournamentKeys.dashboard(id), queryFn: () => getTournamentDashboard(id), refetchInterval: 30_000, staleTime: 0 })
  const refused = dashboard.error instanceof ApiError && (dashboard.error.status === 403 || dashboard.error.status === 404)
  const d = dashboard.data
  const t = tournament.data

  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <BackLink to={`/tournaments/${id}`}>{t?.name ?? d?.name ?? "Tournament"}</BackLink>
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-[32px] leading-9 font-bold">Dashboard</h1>
          {d && <TournamentStatusChip status={d.status} />}
        </div>
        <p className="text-muted-foreground">Entries, check-ins, draws, matches and corrections in every event, and what needs you next.</p>
      </header>
      {dashboard.isPending && <p className="text-muted-foreground">Loading…</p>}
      {refused && <AccessLost />}
      {dashboard.isError && !refused && <FormAlert>{errorMessage(dashboard.error, "We couldn't load the dashboard.")}</FormAlert>}
      {d && (
        <>
          <Totals dashboard={d} />
          <Desks dashboard={d} />
          <section aria-labelledby="events-heading" className="flex flex-col gap-3">
            <h2 id="events-heading" className="text-2xl font-bold">
              Events
            </h2>
            {d.events.length === 0 && <p className="text-muted-foreground">No events yet.</p>}
            <ul className="grid gap-3 md:grid-cols-2">
              {d.events.map((event) => (
                <li key={event.id} className="flex">
                  <EventPanel dashboard={d} event={event} format={t?.events.find((e) => e.id === event.id)?.format} />
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}

/**
 * The tournament-wide desks in one row, each while it applies, by the same rules as the tournament page's
 * manage section: tables and scoring only once the tournament has started. Entry and draw desks are per event.
 */
function Desks({ dashboard: d }: { dashboard: TournamentDashboard }) {
  const running = d.status === "published" || d.status === "in_progress"
  const shown: [Desk, boolean][] = [
    ["schedule", running],
    ["tables", d.status === "in_progress"],
    ["scoring", d.status === "in_progress"],
    ["corrections", d.status === "in_progress" || d.corrections > 0],
    ["ceremony", d.status !== "draft" && d.status !== "cancelled"],
  ]
  const desks = shown.filter(([, on]) => on).map(([desk]) => desk)
  if (desks.length === 0) return null
  return (
    <nav aria-label="Tournament desks" className="flex flex-wrap gap-2">
      {desks.map((desk) => (
        <Link key={desk} to={deskPath(d.id, desk)} className={buttonVariants({ variant: "outline", className: "border-border bg-card" })}>
          {desk === "ceremony" ? `${DESK.ceremony.label}: ${CEREMONY_LABEL[d.ceremony].toLowerCase()}` : DESK[desk].label}
        </Link>
      ))}
    </nav>
  )
}

function Totals({ dashboard: d }: { dashboard: TournamentDashboard }) {
  const tiles: { label: string; value: string; note?: string; attention?: boolean }[] = [
    { label: "Accepted entries", value: String(d.entries.accepted), note: d.entries.waitlisted ? `${d.entries.waitlisted} waitlisted` : undefined },
    { label: "To decide", value: String(d.entries.pending), attention: d.entries.pending > 0 },
    { label: "Checked in", value: String(d.entries.checked_in), note: `of ${d.entries.accepted} accepted` },
    { label: "Matches decided", value: String(d.matches.decided), note: `of ${d.matches.total}` },
    { label: "On a table", value: String(d.matches.on_table), note: `${d.matches.ready} ready to send` },
    { label: "Open corrections", value: String(d.corrections), attention: d.corrections > 0 },
  ]
  return (
    <section aria-label="Totals" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {tiles.map((tile) => (
        <div key={tile.label} className={cn("flex flex-col gap-1 rounded-xl border bg-card p-3", tile.attention && "border-brand-blue/40")}>
          <span className="text-sm text-muted-foreground">{tile.label}</span>
          <span className="flex items-center gap-1.5 text-[28px] leading-8 font-bold tabular-nums">
            {tile.value}
            {tile.attention && <CircleAlert role="img" aria-label="Needs attention" className="size-5 text-brand-blue" />}
          </span>
          {tile.note && <span className="text-sm text-muted-foreground">{tile.note}</span>}
        </div>
      ))}
    </section>
  )
}

/** A count against its whole as a thin bar: the figures are printed beside it, so the bar is never the only reading. */
function Meter({ label, value, of }: { label: string; value: number; of: number | null }) {
  const share = of ? Math.min(1, value / of) : 0
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-semibold tabular-nums">{of === null ? value : `${value} of ${of}`}</span>
      </div>
      {of !== null && (
        <div role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={of} aria-valuenow={value} className="h-2 overflow-hidden rounded-full bg-brand-blue/15">
          <div className="h-full rounded-full bg-brand-blue" style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  )
}

function EventPanel({ dashboard: d, event, format }: { dashboard: TournamentDashboard; event: EventDashboard; format?: Tournament["events"][number]["format"] }) {
  const eventBase = `/tournaments/${d.id}/events/${event.id}`
  const open = event.status !== "completed" && event.status !== "cancelled"
  const next: { text: string; desk?: Desk }[] = []
  if (open && event.entries.pending > 0) next.push({ text: `${count(event.entries.pending, "entry waits", "entries wait")} for a decision on the entry desk.` })
  if (event.status === "scheduled" && event.draw !== "published" && d.status !== "draft")
    next.push({ text: event.draw === "preview" ? "Check the preview on the draw desk and publish the draw." : "Make the draw once entries are settled." })
  if (event.corrections > 0) next.push({ text: `${count(event.corrections, "correction is", "corrections are")} still open.`, desk: "corrections" })
  if (d.status === "in_progress" && event.matches.ready > 0) next.push({ text: `${count(event.matches.ready, "match is", "matches are")} ready for a table.`, desk: "tables" })

  return (
    <article aria-label={event.name} className="flex w-full flex-col gap-3 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="min-w-0 text-xl font-bold break-words">{event.name}</h3>
        <EventStatusChip status={event.status} />
      </div>
      <Meter label="Accepted entries" value={event.entries.accepted} of={event.capacity} />
      <p className="-mt-2 text-sm text-muted-foreground">
        {[
          event.capacity === null && "no entry limit",
          event.entries.waitlisted > 0 && `${event.entries.waitlisted} waitlisted`,
          `${event.entries.checked_in} checked in`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <p className="text-sm font-semibold">{DRAW_LABEL[event.draw]}</p>
      {event.draw === "published" && (
        <>
          <Meter label="Matches decided" value={event.matches.decided} of={event.matches.total} />
          <p className="-mt-2 text-sm text-muted-foreground">
            {event.matches.on_table} on a table · {event.matches.ready} ready
          </p>
        </>
      )}
      <div className="flex flex-col gap-3 border-t pt-3">
        {next.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CircleCheck aria-hidden className="size-4 text-success" /> Nothing waiting on you.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {next.map((item) => (
              <li key={item.text} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="flex items-start gap-2">
                  <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-brand-blue" />
                  {item.text}
                </span>
                {item.desk && (
                  <Link to={deskPath(d.id, item.desk)} className={buttonVariants({ variant: "outline" })}>
                    {DESK[item.desk].label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
        <nav aria-label={`${event.name} desks`} className="flex flex-wrap gap-2">
          <Link to={`${eventBase}/entries`} className={buttonVariants({ variant: "outline" })}>
            Entry desk
          </Link>
          <Link to={`${eventBase}/draw`} className={buttonVariants({ variant: "outline" })}>
            Draw desk
          </Link>
          {event.draw === "published" && format && (
            <Link to={eventTabPath(d.id, event.id, firstTab(format))} className={buttonVariants({ variant: "ghost" })}>
              Draw and results
            </Link>
          )}
        </nav>
      </div>
    </article>
  )
}
