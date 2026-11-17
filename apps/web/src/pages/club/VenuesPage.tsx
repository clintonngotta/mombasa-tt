import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, MapPin, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { AccessLost } from "@/components/clubs/AccessLost"
import { errorMessage } from "@/lib/api"
import { can, useActiveMembership } from "@/lib/clubs"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { cn } from "@/lib/utils"
import { listVenues, tableCount, venueKeys, type Venue } from "@/lib/venues"

/** The organization's venues and how many tables each has (REQ-007), for its facility staff. */
export function VenuesPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "facilities.manage")
  const venues = useQuery({ queryKey: venueKeys.list(orgId), queryFn: () => listVenues(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(venues.error)
  const visible = allowed && !accessLost ? (venues.data ?? []) : []
  const inUse = visible.filter((venue) => venue.active)
  const unused = visible.filter((venue) => !venue.active)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">Venues and tables</h1>
          {active && <p className="text-muted-foreground">{active.organization.name}</p>}
        </div>
        {allowed && (
          <Link to="/club/venues/new" className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> New venue
          </Link>
        )}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {venues.isPending && allowed && <p className="text-muted-foreground">Loading venues…</p>}
      {venues.isError && !accessLost && <FormAlert>{errorMessage(venues.error, "We couldn't load venues.")}</FormAlert>}
      {venues.isSuccess && inUse.length === 0 && !accessLost && (
        <p className="rounded-xl border border-dashed bg-card p-6 text-muted-foreground">
          No venues yet. Add the hall you play in and its tables; tournaments are held at a venue.
        </p>
      )}
      <VenueList venues={inUse} />
      {unused.length > 0 && (
        <section aria-labelledby="unused-venues-heading" className="flex flex-col gap-3">
          <h2 id="unused-venues-heading" className="text-xl font-bold">
            No longer in use
          </h2>
          <VenueList venues={unused} />
        </section>
      )}
    </div>
  )
}

function VenueList({ venues }: { venues: Venue[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {venues.map((venue) => (
        <li key={venue.id}>
          <Link to={`/club/venues/${venue.id}`} className={cn(ROW, "min-h-12 outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
            <MapPin aria-hidden className="size-5 text-brand-blue" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="font-semibold break-words">{venue.name}</span>
              <span className="text-sm text-muted-foreground">
                {venue.town} · {tableCount(venue)}
              </span>
            </span>
            <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  )
}
