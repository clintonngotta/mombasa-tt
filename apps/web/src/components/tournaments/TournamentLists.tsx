import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight } from "lucide-react"
import { EntryStatusChip } from "@/components/tournaments/StatusChip"
import { LiveBadge } from "@/components/tournaments/LiveScore"
import { formatDayRange } from "@/lib/dates"
import { entryKeys, entryTitle, isLive, listMyEntries } from "@/lib/entries"
import { useMe } from "@/lib/session"
import { isClosed, listTournaments, tournamentKeys } from "@/lib/tournaments"

/** Tournaments being played right now, each opening its page, where the live scores are. Nothing at all when none is on. */
export function LiveNow() {
  const upcoming = useQuery({ queryKey: tournamentKeys.list("upcoming", "", ""), queryFn: () => listTournaments("upcoming", "", "") })
  const live = (upcoming.data?.results ?? []).filter((t) => t.status === "in_progress")
  if (live.length === 0) return null
  return (
    <section aria-labelledby="live-now-heading" className="flex flex-col gap-3">
      <h2 id="live-now-heading" className="text-2xl font-bold">
        Being played now
      </h2>
      <ul className="flex flex-col gap-2">
        {live.map((t) => (
          <li key={t.id}>
            <Link
              to={`/tournaments/${t.id}`}
              className="flex items-center gap-3 rounded-xl border border-destructive/40 bg-card p-4 outline-none hover:border-destructive focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <LiveBadge />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold break-words">{t.name}</span>
                <span className="text-sm text-muted-foreground">{[t.venue?.name, t.venue?.town].filter(Boolean).join(", ") || t.organizer.name} · follow the scores</span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The caller's standing entries in tournaments that aren't over; nothing at all when there are none. */
export function MyEntries() {
  const me = useMe()
  const entries = useQuery({ queryKey: entryKeys.mine, queryFn: listMyEntries, enabled: me.isSuccess })
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
