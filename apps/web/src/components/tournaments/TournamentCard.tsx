import { Link } from "react-router-dom"
import { CalendarDays, MapPin } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatDayRange } from "@/lib/dates"
import { countdown, KIND_LABEL, SCOPE_LABEL, type Tournament } from "@/lib/tournaments"
import { TournamentStatusChip } from "@/components/tournaments/StatusChip"
import { CoverBackdrop } from "@/components/tournaments/TournamentMedia"

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
      <CoverBackdrop cover={t.cover} coverClassName="-mx-4 -mt-4 rounded-t-xl">
        {(onCover) => (
          <div className={cn("flex flex-col gap-3", onCover && "p-4")}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className={cn("flex items-center gap-1.5 text-sm font-semibold", !onCover && "text-muted-foreground")}>
                <CalendarDays aria-hidden className="size-4" />
                {formatDayRange(t.starts_on, t.ends_on)}
              </span>
              {/* "Published" is the normal state of a listed tournament, so only the others are called out. */}
              {t.status !== "published" && (
                <span className={cn("inline-flex shrink-0 rounded-full", onCover && "bg-card")}>
                  <TournamentStatusChip status={t.status} />
                </span>
              )}
            </div>
            <span className={cn("font-display text-2xl leading-7 font-bold break-words", onCover && "[text-shadow:0_1px_3px_rgb(0_0_0/0.6)]")}>{t.name}</span>
          </div>
        )}
      </CoverBackdrop>
      <div className="flex flex-col gap-1">
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
