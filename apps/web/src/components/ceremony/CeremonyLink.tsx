import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Trophy } from "lucide-react"
import { ApiError } from "@/lib/api"
import { ceremonyKeys, getCeremony } from "@/lib/ceremony"
import { ROW } from "@/lib/clubAdmin"
import { cn } from "@/lib/utils"

/** The way to a tournament's award ceremony: for its competition staff once the tournament is out, for
 * everyone else once the ceremony is published. */
export function CeremonyLink({ tournamentId, staff, open }: { tournamentId: string; staff: boolean; open: boolean }) {
  const ceremony = useQuery({
    queryKey: ceremonyKeys.detail(tournamentId),
    queryFn: () => getCeremony(tournamentId).catch((error) => (error instanceof ApiError && error.status === 404 ? null : Promise.reject(error))),
  })
  if (!(staff && open) && !ceremony.data) return null
  const c = ceremony.data
  return (
    <Link to={`/tournaments/${tournamentId}/ceremony`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
      <Trophy aria-hidden className="size-5 text-brand-gold" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="font-semibold">Award ceremony</span>
        <span className="text-sm text-muted-foreground">
          {!c ? "Plan the awards, their order and who presents them" : c.status === "draft" ? `Draft · ${c.awards.length} awards` : c.status === "done" ? "All awards presented" : `${c.awards.length} awards`}
        </span>
      </span>
      <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
    </Link>
  )
}
