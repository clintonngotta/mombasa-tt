import { Link } from "react-router-dom"
import { CalendarDays, MapPin } from "lucide-react"
import { formatDayRange } from "@/lib/dates"
import { countdown, KIND_LABEL, SCOPE_LABEL, type Tournament } from "@/lib/tournaments"
import { TournamentStatusChip } from "@/components/tournaments/StatusChip"
import { TournamentCover } from "@/components/tournaments/TournamentMedia"

/**
 * A tournament in a list: its cover, dates, name, organizer and venue, its events as chips and a countdown.
 * It opens the tournament's page, or `to` (the organizer's list opens dashboards).
 */
export function TournamentCard({ tournament: t, to = `/tournaments/${t.id}` }: { tournament: Tournament; to?: string }) {
  const soon = countdown(t)
  const events = t.events.filter((e) => e.status !== "cancelled")
  return (
    <Link
      to={to}
      className="flex flex-col gap-3 overflow-hidden rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      <TournamentCover cover={t.cover} className="-mx-4 -mt-4 aspect-[16/6] w-[calc(100%+2rem)] max-w-none rounded-t-xl bg-surface-selected object-cover" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
          <CalendarDays aria-hidden className="size-4" />
          {formatDayRange(t.starts_on, t.ends_on)}
        </span>
        {/* "Published" is the normal state of a listed tournament, so only the others are called out. */}
        {t.status !== "published" && <TournamentStatusChip status={t.status} />}
      </div>
      <div className="flex flex-col gap-1">
        <span className="font-display text-2xl leading-7 font-bold break-words">{t.name}</span>
        <span className="flex items-start gap-1 text-sm text-muted-foreground">
          <MapPin aria-hidden className="mt-0.5 size-4 shrink-0" />
          <span className="break-words">{[SCOPE_LABEL[t.scope], t.venue?.name, t.venue?.town].filter(Boolean).join(" · ")}</span>
        </span>
        <span className="text-sm text-muted-foreground">
          Organized by <span className="font-semibold text-foreground">{t.organizer.name}</span> · {t.organizer.label}
        </span>
      </div>
      {(events.length > 0 || soon) && (
        <div className="flex flex-wrap items-center gap-2">
          {events.map((e) => (
            <span key={e.id} className="rounded-full bg-surface-selected px-2.5 py-0.5 text-sm font-semibold text-brand-navy">
              {e.name || KIND_LABEL[e.kind]}
            </span>
          ))}
          {soon && <span className="ml-auto text-sm font-semibold text-brand-blue">{soon}</span>}
        </div>
      )}
    </Link>
  )
}
