import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { TournamentCard } from "@/components/tournaments/TournamentCard"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { useAdminAccessLost } from "@/lib/clubAdmin"
import { listHostedTournaments, tournamentKeys } from "@/lib/tournaments"

/**
 * The organizer's way in (REQ-007, TASK-035): every tournament the active organization hosts, drafts
 * included, each opening its dashboard, where its desks are. Players' view of a tournament is its own page.
 */
export function TournamentDashboardsPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "competitions.manage")
  const hosted = useQuery({ queryKey: tournamentKeys.hosted(orgId), queryFn: () => listHostedTournaments(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(hosted.error)
  const items = allowed && !accessLost ? (hosted.data?.results ?? []) : []

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">Tournaments</h1>
          {active && <p className="text-muted-foreground">Hosted by {active.organization.name}. Open one for its dashboard.</p>}
        </div>
        {allowed && (
          <Link to="/club/tournaments/new" className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> New tournament
          </Link>
        )}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {hosted.isPending && allowed && <p className="text-muted-foreground">Loading tournaments…</p>}
      {hosted.isError && !accessLost && <FormAlert>{errorMessage(hosted.error, "We couldn't load your tournaments.")}</FormAlert>}
      {hosted.isSuccess && items.length === 0 && !accessLost && (
        <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">
          No tournaments yet. Create a draft, add its events, then publish it for players to see.
        </p>
      )}
      <ul className="flex flex-col gap-3">
        {items.map((tournament) => (
          <li key={tournament.id} className="flex flex-col gap-2">
            <TournamentCard tournament={tournament} to={`/tournaments/${tournament.id}/dashboard`} />
            <Link to={`/tournaments/${tournament.id}`} aria-label={`Tournament page of ${tournament.name}`} className={buttonVariants({ variant: "ghost", className: "self-start" })}>
              Tournament page
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
