import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, Search } from "lucide-react"
import {
  CalendarBody,
  CalendarDate,
  CalendarDatePagination,
  CalendarDatePicker,
  CalendarHeader,
  CalendarItem,
  CalendarMonthPicker,
  CalendarProvider,
  CalendarYearPicker,
  useCalendarMonth,
  useCalendarYear,
  type Feature,
} from "@/components/kibo-ui/calendar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { Segmented } from "@/components/forms/Segmented"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { coachingKeys, getCalendar, isoDay, weekOf, type CalendarEntry, type CoachProfile } from "@/lib/coaching"
import { formatDay, formatDayRange, formatInstant } from "@/lib/dates"
import { LOCAL_TIME_ZONE } from "@/lib/training"
import { cn } from "@/lib/utils"

type Kind = CalendarEntry["kind"]
type View = "month" | "week"

const KINDS: { kind: Kind; label: string; color: string }[] = [
  { kind: "booking", label: "Session", color: "var(--brand-blue)" },
  { kind: "trainee_session", label: "Trainee's plan", color: "var(--brand-gold)" },
  { kind: "session", label: "My training", color: "var(--brand-cyan)" },
  { kind: "club_session", label: "Club training", color: "var(--status-success)" },
  { kind: "tournament", label: "Tournament", color: "var(--brand-navy)" },
]
const KIND = Object.fromEntries(KINDS.map((k) => [k.kind, k])) as Record<Kind, (typeof KINDS)[number]>
const VIEWS: { value: View; label: string }[] = [
  { value: "month", label: "Month" },
  { value: "week", label: "Week" },
]
const THIS_YEAR = new Date().getFullYear()

const localDay = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number)
  return new Date(y, m - 1, d)
}
const nextDay = (iso: string) => {
  const day = localDay(iso)
  day.setDate(day.getDate() + 1)
  return isoDay(day)
}

/** The first and last day an entry falls on, in the coach's timezone, kept inside the shown range. */
function span(entry: CalendarEntry, timeZone: string, from: string, to: string) {
  const zoned = (iso: string) => new Intl.DateTimeFormat("en-CA", { timeZone }).format(new Date(iso))
  const first = entry.starts_at ? zoned(entry.starts_at) : (entry.starts_on ?? from)
  const last = entry.starts_at ? first : (entry.ends_on ?? first)
  return { first: first < from ? from : first, last: last > to ? to : last }
}

/** The coach's calendar (REQ-047): a month grid or a week, with every day's entries listed underneath.
 * Search and the kind filters narrow both. Sessions, the coach's own and their trainees' planned training,
 * their clubs' training and tournaments are shown; each entry opens what it is about. */
export function CoachCalendar({ profile }: { profile: CoachProfile }) {
  const timeZone = profile.timezone ?? LOCAL_TIME_ZONE
  const [view, setView] = useState<View>("month")
  const [search, setSearch] = useState("")
  const [hidden, setHidden] = useState<ReadonlySet<Kind>>(new Set())
  const [weekAnchor, setWeekAnchor] = useState(() => new Date())
  const [month] = useCalendarMonth()
  const [year] = useCalendarYear()

  const range = view === "week" ? weekOf(weekAnchor) : { from: isoDay(new Date(year, month, 1)), to: isoDay(new Date(year, month + 1, 0)) }
  const { from, to } = range
  const calendar = useQuery({ queryKey: coachingKeys.calendar(from, to), queryFn: () => getCalendar(from, to) })

  const term = search.trim().toLowerCase()
  const entries = useMemo(
    () =>
      (calendar.data ?? []).filter(
        (entry) => !hidden.has(entry.kind) && (!term || `${entry.title} ${entry.detail ?? ""} ${KIND[entry.kind].label}`.toLowerCase().includes(term))
      ),
    [calendar.data, hidden, term]
  )

  // One mark per day an entry covers, so a three-day tournament shows on all three.
  const features = useMemo(() => {
    const marks: (Feature & { entry: CalendarEntry })[] = []
    for (const entry of entries) {
      const { first, last } = span(entry, timeZone, from, to)
      for (let day = first; day <= last; day = nextDay(day)) {
        const at = localDay(day)
        marks.push({ id: `${entry.kind}-${entry.id}-${day}`, name: entry.title, startAt: at, endAt: at, status: { id: entry.kind, name: KIND[entry.kind].label, color: KIND[entry.kind].color }, entry })
      }
    }
    return marks
  }, [entries, timeZone, from, to])

  const byDay = new Map<string, CalendarEntry[]>()
  for (const entry of entries) {
    const { first } = span(entry, timeZone, from, to)
    byDay.set(first, [...(byDay.get(first) ?? []), entry])
  }
  const days = [...byDay.entries()].sort(([a], [b]) => a.localeCompare(b))
  const total = calendar.data?.length ?? 0
  const filtering = term !== "" || hidden.size > 0

  const toggle = (kind: Kind) =>
    setHidden((current) => {
      const next = new Set(current)
      if (!next.delete(kind)) next.add(kind)
      return next
    })
  const moveWeek = (days: number) =>
    setWeekAnchor((d) => {
      const next = new Date(d)
      next.setDate(d.getDate() + days)
      return next
    })

  return (
    <section aria-labelledby="calendar-heading" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="calendar-heading" className="text-xl font-bold">
          Calendar <span className="text-base font-normal text-muted-foreground">{formatDayRange(from, to)}</span>
        </h2>
        <Segmented label="Calendar view" options={VIEWS} value={view} onChange={setView} />
      </div>

      <div className="flex flex-col gap-3 rounded-xl border bg-card p-3">
        <div className="relative">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input type="search" aria-label="Search the calendar" placeholder="Search by player, club, tournament or venue" maxLength={80} className="pl-9" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div role="group" aria-label="Show" className="flex flex-wrap gap-2">
          {KINDS.map(({ kind, label, color }) => {
            const on = !hidden.has(kind)
            return (
              <button
                key={kind}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(kind)}
                className={cn(
                  "flex min-h-10 items-center gap-2 rounded-full border px-3 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  on ? "bg-surface-selected text-foreground" : "text-muted-foreground line-through"
                )}
              >
                <span aria-hidden className="size-2.5 rounded-full" style={{ backgroundColor: color, opacity: on ? 1 : 0.35 }} />
                {label}
              </button>
            )
          })}
          {filtering && (
            <Button variant="ghost" onClick={() => { setSearch(""); setHidden(new Set()) }}>
              Clear filters
            </Button>
          )}
        </div>
      </div>

      {view === "month" ? (
        <CalendarProvider locale="en-KE" startDay={1} className="overflow-hidden rounded-xl border bg-card">
          <CalendarDate>
            <CalendarDatePicker>
              <CalendarMonthPicker />
              <CalendarYearPicker start={THIS_YEAR - 2} end={THIS_YEAR + 2} />
            </CalendarDatePicker>
            <CalendarDatePagination />
          </CalendarDate>
          <CalendarHeader />
          <CalendarBody features={features}>
            {({ feature }) => {
              const { entry } = feature as (typeof features)[number]
              const waiting = entry.kind === "booking" && entry.status === "requested"
              const item = <CalendarItem feature={feature} className={cn("text-foreground", waiting && "italic")} />
              return entry.link ? (
                <Link key={feature.id} to={entry.link} title={`${entry.title} · ${KIND[entry.kind].label}`} className="block rounded outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50">
                  {item}
                </Link>
              ) : (
                <div key={feature.id} title={`${entry.title} · ${KIND[entry.kind].label}`}>
                  {item}
                </div>
              )
            }}
          </CalendarBody>
        </CalendarProvider>
      ) : (
        <div className="flex justify-end gap-1">
          <Button variant="outline" size="icon" aria-label="Previous week" onClick={() => moveWeek(-7)}>
            <ChevronLeft aria-hidden className="size-5" />
          </Button>
          <Button variant="outline" onClick={() => setWeekAnchor(new Date())}>
            This week
          </Button>
          <Button variant="outline" size="icon" aria-label="Next week" onClick={() => moveWeek(7)}>
            <ChevronRight aria-hidden className="size-5" />
          </Button>
        </div>
      )}

      {calendar.isError && <FormAlert>{errorMessage(calendar.error, "We couldn't load your calendar.")}</FormAlert>}
      <div aria-live="polite" className="flex flex-col gap-4">
        {calendar.isSuccess && entries.length === 0 && (
          <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">
            {total === 0
              ? `Nothing this ${view}. Sessions, your clubs' training and tournaments appear here.`
              : `Nothing matches. ${total} ${total === 1 ? "entry is" : "entries are"} hidden by the search or filters.`}
          </p>
        )}
        {calendar.isSuccess && filtering && entries.length > 0 && (
          <p className="text-sm text-muted-foreground">
            Showing {entries.length} of {total}
          </p>
        )}
        <ol className="flex flex-col gap-4">
          {days.map(([day, list]) => (
            <li key={day} className="flex flex-col gap-2">
              <h3 className="font-semibold">{formatDay(day)}</h3>
              <ul className="flex flex-col gap-2">
                {list.map((entry) => (
                  <li key={`${entry.kind}-${entry.id}`}>
                    <Entry entry={entry} day={day} timeZone={timeZone} />
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function Entry({ entry, day, timeZone }: { entry: CalendarEntry; day: string; timeZone: string }) {
  const waiting = entry.kind === "booking" && entry.status === "requested"
  const body = (
    <>
      <span aria-hidden className="size-2.5 shrink-0 rounded-full" style={{ backgroundColor: KIND[entry.kind].color }} />
      <span className="w-28 shrink-0 text-sm font-semibold tabular-nums">
        {entry.starts_at && entry.ends_at
          ? `${formatInstant(entry.starts_at, timeZone).slice(-5)}–${formatInstant(entry.ends_at, timeZone).slice(-5)}`
          : formatDayRange(entry.starts_on ?? day, entry.ends_on ?? day)}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-semibold">{entry.title}</span>
        <span className="text-sm text-muted-foreground">
          {KIND[entry.kind].label}
          {waiting && " · waiting for you"}
          {entry.detail && ` · ${entry.detail}`}
        </span>
      </span>
    </>
  )
  return entry.link ? (
    <Link to={entry.link} className={cn(ROW, "flex-nowrap outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50")}>
      {body}
    </Link>
  ) : (
    <div className={cn(ROW, "flex-nowrap", waiting && "border-dashed")}>{body}</div>
  )
}
