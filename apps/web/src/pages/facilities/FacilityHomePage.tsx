import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { DoorOpen, MapPin } from "lucide-react"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { OrganizationLinks } from "@/components/clubs/OrganizationLinks"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { can, useActiveMembership, type Membership } from "@/lib/clubs"
import { actsAsFacility } from "@/lib/navigation"
import { listVenues, tableCount, venueKeys } from "@/lib/venues"
import { cn } from "@/lib/utils"

/** A facility's own home (REQ-044). A facility isn't a person: it has branches, a front desk, takings and
 * staff, not matches or ratings, so it gets its own menu and starts here. */
export function FacilityHomePage() {
  const { memberships, active } = useActiveMembership()
  if (memberships.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (!active || !actsAsFacility(active)) {
    return (
      <div className="flex max-w-[640px] flex-col items-start gap-3">
        <FormAlert>Switch to a facility you work for to open its desk.</FormAlert>
        <Link to="/club" className={buttonVariants({ variant: "outline" })}>
          Go to your club
        </Link>
      </div>
    )
  }
  return <FacilityHome membership={active} />
}

function FacilityHome({ membership }: { membership: Membership }) {
  const organization = membership.organization
  const desk = can(membership, "facilities.manage")
  const venues = useQuery({ queryKey: venueKeys.list(organization.id), queryFn: () => listVenues(organization.id), enabled: desk })
  const open = (venues.data ?? []).filter((venue) => venue.active)

  return (
    <div className="flex max-w-[720px] flex-col gap-8">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold tracking-wide text-brand-blue uppercase">Facility desk</p>
        <h1 className="text-[32px] leading-9 font-bold">{organization.name}</h1>
        {organization.town && <p className="text-muted-foreground">{[organization.town, organization.region].filter(Boolean).join(", ")}</p>}
      </div>

      {desk && (
        <section aria-labelledby="branches-heading" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="branches-heading" className="text-xl font-bold">
              Branches today
            </h2>
            <Link to="/club/venues/new" className={buttonVariants({ variant: "outline", size: "sm" })}>
              Add a branch
            </Link>
          </div>
          {venues.isPending && <p className="text-muted-foreground">Loading branches…</p>}
          {venues.isError && <FormAlert>{errorMessage(venues.error, "We couldn't load your branches.")}</FormAlert>}
          {venues.isSuccess && open.length === 0 && <p className="text-muted-foreground">No branches yet. Add one to take bookings and walk-ins.</p>}
          <ul className="flex flex-col gap-2">
            {open.map((venue) => (
              <li key={venue.id} className={cn(ROW, "flex-wrap")}>
                <MapPin aria-hidden className="size-5 shrink-0 text-brand-blue" />
                <Link to={`/club/venues/${venue.id}`} className="flex min-w-0 flex-1 flex-col rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                  <span className="truncate font-semibold">{venue.name}</span>
                  <span className="text-sm text-muted-foreground">
                    {tableCount(venue)}
                    {venue.town && ` · ${venue.town}`}
                  </span>
                </Link>
                <Link to={`/club/venues/${venue.id}/door`} className={buttonVariants()}>
                  <DoorOpen aria-hidden className="size-5" /> Door
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <OrganizationLinks membership={membership} variant="facility" />
    </div>
  )
}
