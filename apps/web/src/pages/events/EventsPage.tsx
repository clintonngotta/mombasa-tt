import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { CalendarDays, ExternalLink, Flag, List, Radio } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { SelectField } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { formatDayRange } from "@/lib/dates"
import { CATEGORY_LABEL, countdown, eventKeys, listEvents, reportLiveLink, type EventFilters, type ListedEvent } from "@/lib/events"
import { useMe } from "@/lib/session"
import { cn } from "@/lib/utils"

const monthStart = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1)
const iso = (d: Date) => d.toLocaleDateString("en-CA")
const STATUS: Record<string, string> = { postponed: "Postponed", cancelled: "Cancelled", completed: "Finished" }

/** Table tennis events in the country (REQ-042): on Coast TT and elsewhere, as a list or a month. */
export function EventsPage() {
  const me = useMe()
  const signedIn = !!me.data
  const [view, setView] = useState<"list" | "month">("list")
  const [month, setMonth] = useState(() => monthStart(new Date()))
  const [when, setWhen] = useState<"upcoming" | "past">("upcoming")
  const [town, setTown] = useState("")
  const [category, setCategory] = useState("")
  const [ours, setOurs] = useState(false)
  const monthEnd = new Date(month.getFullYear(), month.getMonth() + 1, 0)
  const filters: EventFilters =
    view === "month" ? { when: "", from: iso(month), to: iso(monthEnd), town, category, ours } : { when, from: "", to: "", town, category, ours }
  const events = useQuery({ queryKey: eventKeys.list(filters), queryFn: () => listEvents(filters) })

  return (
    <div className="flex max-w-[860px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Events</h1>
        <p className="text-muted-foreground">Table tennis tournaments and events in the country, on Coast TT and elsewhere.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="View" className="flex rounded-lg border bg-card p-1">
          {(
            [
              ["list", "List", List],
              ["month", "Month", CalendarDays],
            ] as const
          ).map(([value, label, Icon]) => (
            <button key={value} type="button" aria-pressed={view === value} onClick={() => setView(value)} className={cn("flex h-12 items-center gap-2 rounded-md px-4 font-semibold text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50", view === value && "bg-surface-selected text-brand-blue")}>
              <Icon aria-hidden className="size-4" /> {label}
            </button>
          ))}
        </div>
        {view === "list" ? (
          <div role="group" aria-label="Which events" className="flex rounded-lg border bg-card p-1">
            {(["upcoming", "past"] as const).map((value) => (
              <button key={value} type="button" aria-pressed={when === value} onClick={() => setWhen(value)} className={cn("h-12 rounded-md px-4 font-semibold text-muted-foreground capitalize outline-none focus-visible:ring-3 focus-visible:ring-ring/50", when === value && "bg-surface-selected text-brand-blue")}>
                {value}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} aria-label="Previous month">
              ‹
            </Button>
            <span className="min-w-36 text-center font-semibold">{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</span>
            <Button variant="outline" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} aria-label="Next month">
              ›
            </Button>
          </div>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Town" optional value={town} onChange={(e) => setTown(e.target.value)} placeholder="Mombasa" />
        <SelectField label="Category" value={category} onChange={setCategory} options={[{ value: "", label: "All" }, ...Object.entries(CATEGORY_LABEL).map(([value, label]) => ({ value, label }))]} />
        {signedIn && (
          <label className="flex min-h-12 items-center gap-3 self-end font-semibold">
            <input type="checkbox" className="size-5 accent-brand-blue" checked={ours} onChange={(e) => setOurs(e.target.checked)} />
            Our club only
          </label>
        )}
      </div>
      {events.isError && <FormAlert>{errorMessage(events.error, "We couldn't load the events.")}</FormAlert>}
      {events.isSuccess && events.data.length === 0 && <p className="text-muted-foreground">No events match.</p>}
      {view === "month" && events.data ? (
        <MonthGrid month={month} events={events.data} />
      ) : (
        <ul className="flex flex-col gap-3">
          {(events.data ?? []).map((event) => (
            <li key={`${event.kind}-${event.id}`}>
              <EventCard event={event} signedIn={signedIn} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function EventCard({ event, signedIn }: { event: ListedEvent; signedIn: boolean }) {
  const [reported, setReported] = useState(false)
  const report = useMutation({ mutationFn: () => reportLiveLink(event.id, "broken"), onSuccess: () => setReported(true) })
  const soon = event.status === "scheduled" ? countdown(event.starts_on) : ""
  const title = event.kind === "coast" ? (
    <Link to={`/tournaments/${event.id}`} className="text-lg font-bold text-brand-blue underline-offset-4 hover:underline">
      {event.name}
    </Link>
  ) : (
    <span className="text-lg font-bold">{event.name}</span>
  )
  return (
    <article className="flex flex-col gap-1.5 rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        {title}
        {event.live && (
          <span className="flex items-center gap-1 rounded-full bg-destructive px-2.5 py-0.5 text-sm font-bold text-white">
            <Radio aria-hidden className="size-3.5" /> Live
          </span>
        )}
        {event.review === "pending" && <span className="rounded-full bg-muted px-2.5 py-0.5 text-sm font-semibold">Awaiting review</span>}
        {STATUS[event.status] && <span className="rounded-full bg-muted px-2.5 py-0.5 text-sm font-semibold">{STATUS[event.status]}</span>}
      </div>
      <p className="text-sm text-muted-foreground">
        {formatDayRange(event.starts_on, event.ends_on)}
        {soon && ` · ${soon}`} · {[event.venue, event.town].filter(Boolean).join(", ")} · {event.organizer}
        {event.kind === "external" && " · not on Coast TT"}
      </p>
      {event.categories.length > 0 && <p className="text-sm">{event.categories.map((c) => CATEGORY_LABEL[c] ?? c).join(" · ")}</p>}
      {event.entry_info && <p className="text-sm whitespace-pre-wrap">{event.entry_info}</p>}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {event.kind === "coast" && event.live && (
          <Link to={`/tournaments/${event.id}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
            Follow it live
          </Link>
        )}
        {event.live_url && (
          <a href={event.live_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 font-semibold text-brand-blue underline-offset-4 hover:underline">
            Watch live on {event.live_domain} <ExternalLink aria-hidden className="size-3.5" />
          </a>
        )}
        {event.info_url && (
          <a href={event.info_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 text-brand-blue underline-offset-4 hover:underline">
            Details on {event.info_domain} <ExternalLink aria-hidden className="size-3.5" />
          </a>
        )}
        {event.live_url && signedIn && (
          <button type="button" disabled={reported || report.isPending} onClick={() => report.mutate()} className="flex items-center gap-1 text-muted-foreground underline-offset-4 hover:underline disabled:no-underline">
            <Flag aria-hidden className="size-3.5" /> {reported ? "Reported, thank you" : "Link not working?"}
          </button>
        )}
      </div>
    </article>
  )
}

function MonthGrid({ month, events }: { month: Date; events: ListedEvent[] }) {
  const first = monthStart(month)
  const lead = (first.getDay() + 6) % 7 // Monday first
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const cells = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)]
  const on = (day: number) => {
    const date = iso(new Date(month.getFullYear(), month.getMonth(), day))
    return events.filter((e) => e.starts_on <= date && date <= e.ends_on)
  }
  return (
    <div className="grid grid-cols-7 gap-1 text-sm">
      {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
        <div key={d} className="p-1 text-center font-semibold text-muted-foreground">
          {d}
        </div>
      ))}
      {cells.map((day, i) => (
        <div key={i} className={cn("min-h-20 rounded-md border p-1", !day && "border-transparent")}>
          {day && <div className="text-xs font-semibold text-muted-foreground">{day}</div>}
          {day &&
            on(day).map((e) =>
              e.kind === "coast" ? (
                <Link key={e.id} to={`/tournaments/${e.id}`} className={cn("block truncate rounded bg-brand-blue/10 px-1 text-brand-blue", e.status === "cancelled" && "line-through")}>
                  {e.name}
                </Link>
              ) : (
                <span key={e.id} className={cn("block truncate rounded bg-muted px-1", e.status === "cancelled" && "line-through")}>
                  {e.name}
                </span>
              )
            )}
        </div>
      ))}
    </div>
  )
}
