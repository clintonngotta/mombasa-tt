import { Link, Navigate, Outlet } from "react-router-dom"
import { buttonVariants } from "@/components/ui/button"
import { actsAsFacility } from "@/lib/navigation"
import { useActiveMembership } from "@/lib/clubs"

/** Play, training, rankings and coaching are a person's own. While someone acts for a facility, which
 * isn't a person, these pages point back to the facility desk instead. */
export function PersonOnly() {
  const { active } = useActiveMembership()
  if (!actsAsFacility(active)) return <Outlet />
  return (
    <div className="flex max-w-[640px] flex-col items-start gap-3">
      <h1 className="text-2xl font-bold">Not available for a facility</h1>
      <p className="text-muted-foreground">
        Play, training and rankings belong to players. You're acting for {active?.organization.name}; switch to a
        club you belong to in the organization menu to use them.
      </p>
      <Link to="/facility" className={buttonVariants()}>
        Back to the facility desk
      </Link>
    </div>
  )
}

/** Home for a person; a facility's home is its desk. */
export function HomeRoute() {
  const { active } = useActiveMembership()
  return actsAsFacility(active) ? <Navigate to="/facility" replace /> : null
}
