import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Medal, Trophy } from "lucide-react"
import { ceremonyKeys, listHonours, PLACE_MEDAL } from "@/lib/ceremony"
import { formatDay } from "@/lib/dates"
import { cn } from "@/lib/utils"

/** The awards the player received at published ceremonies (REQ-049). Hidden while there are none. */
export function Honours() {
  const honours = useQuery({ queryKey: ceremonyKeys.honours, queryFn: listHonours })
  if (!honours.data?.length) return null
  return (
    <section aria-labelledby="honours-heading" className="flex flex-col gap-3">
      <h2 id="honours-heading" className="text-xl font-bold">
        Honours
      </h2>
      <ul className="flex flex-col gap-2">
        {honours.data.map((honour) => (
          <li key={honour.id}>
            <Link to={`/tournaments/${honour.tournament}/ceremony`} className="flex items-center gap-3 rounded-xl border bg-card p-3 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
              {honour.place ? (
                <Medal aria-label={`${PLACE_MEDAL[honour.place]} medal`} className={cn("size-6", honour.place === 1 ? "text-brand-gold" : honour.place === 2 ? "text-slate-400" : "text-amber-700")} />
              ) : (
                <Trophy aria-hidden className="size-6 text-brand-blue" />
              )}
              <span className="flex min-w-0 flex-col">
                <span className="font-semibold">{honour.title}</span>
                <span className="text-sm text-muted-foreground">
                  {honour.tournament_name} · {formatDay(honour.held_on)}
                  {honour.prize && ` · ${honour.prize}`}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
