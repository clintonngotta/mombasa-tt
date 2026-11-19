import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CalendarClock, CalendarDays, Newspaper } from "lucide-react"
import { ROW } from "@/lib/clubAdmin"
import { formatDay, formatInstant } from "@/lib/dates"
import { AGENDA_KIND_LABEL, listMyAgenda, listMyArticles, listMyMeetings, regionKeys } from "@/lib/regions"
import { cn } from "@/lib/utils"

const LINK = cn(ROW, "flex-nowrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50")

/** What the region's body sends a club member (REQ-048): meetings they're invited to, news and the
 * coming dates of the regional agenda. Hidden when there is nothing. */
export function RegionFeed() {
  const meetings = useQuery({ queryKey: regionKeys.myMeetings, queryFn: listMyMeetings })
  const articles = useQuery({ queryKey: regionKeys.myArticles, queryFn: listMyArticles })
  const agenda = useQuery({ queryKey: regionKeys.myAgenda, queryFn: listMyAgenda })
  const [now] = useState(() => Date.now())
  const today = new Date(now).toISOString().slice(0, 10)
  const upcomingMeetings = (meetings.data ?? []).filter((m) => m.status === "published" && new Date(m.ends_at).getTime() > now).slice(0, 3)
  const news = (articles.data ?? []).slice(0, 3)
  const dates = (agenda.data ?? []).filter((item) => (item.ends_on ?? item.starts_on) >= today).slice(0, 4)
  if (!upcomingMeetings.length && !news.length && !dates.length) return null

  return (
    <section aria-labelledby="region-feed-heading" className="flex flex-col gap-3">
      <h2 id="region-feed-heading" className="text-xl font-bold">
        From the region
      </h2>
      <ul className="flex flex-col gap-2">
        {upcomingMeetings.map((meeting) => (
          <li key={meeting.id}>
            <Link to={`/meetings/${meeting.organization.id}/${meeting.id}`} className={LINK}>
              <CalendarClock aria-hidden className="size-5 shrink-0 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{meeting.title}</span>
                <span className="text-sm text-muted-foreground">
                  Meeting · {meeting.organization.name} · {formatInstant(meeting.starts_at, "Africa/Nairobi")}
                  {meeting.me?.answer === "none" && " · please answer"}
                </span>
              </span>
            </Link>
          </li>
        ))}
        {news.map((article) => (
          <li key={article.id}>
            <Link to={`/news/${article.organization.id}/${article.id}`} className={LINK}>
              <Newspaper aria-hidden className="size-5 shrink-0 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-semibold">{article.title}</span>
                <span className="truncate text-sm text-muted-foreground">{article.summary || article.organization.name}</span>
              </span>
            </Link>
          </li>
        ))}
        {dates.map((item) => (
          <li key={item.id} className={cn(ROW, "flex-nowrap")}>
            <CalendarDays aria-hidden className="size-5 shrink-0 text-brand-blue" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate font-semibold">
                {item.tournament ? (
                  <Link to={`/tournaments/${item.tournament.id}`} className="text-brand-blue underline-offset-4 hover:underline">
                    {item.title}
                  </Link>
                ) : (
                  item.title
                )}
              </span>
              <span className="text-sm text-muted-foreground">
                {formatDay(item.starts_on)} · {AGENDA_KIND_LABEL[item.kind ?? "event"]} · {item.organization.name}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
