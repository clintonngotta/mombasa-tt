import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Lock, Plus } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { buttonVariants } from "@/components/ui/button"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { can, clubKeys, listRoles, useActiveMembership } from "@/lib/clubs"
import { cn } from "@/lib/utils"
import { AccessLost } from "@/components/clubs/AccessLost"
import { ROW, useAdminAccessLost } from "@/lib/clubAdmin"
import { OrganizationName } from "@/components/clubs/KindBadge"

/** The organization's roles (REQ-005): templates plus custom roles, with member counts. */
export function RolesPage() {
  const { memberships, active } = useActiveMembership()
  const orgId = active?.organization.id ?? ""
  const allowed = can(active, "roles.manage")
  const roles = useQuery({ queryKey: clubKeys.roles(orgId), queryFn: () => listRoles(orgId), enabled: allowed })
  const accessLost = useAdminAccessLost(roles.error)

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-[32px] leading-9 font-bold">Roles</h1>
          {active && <p className="text-muted-foreground"><OrganizationName organization={active.organization} /></p>}
        </div>
        {allowed && (
          <Link to="/club/roles/new" className={buttonVariants({ variant: "outline" })}>
            <Plus aria-hidden className="size-5" /> New role
          </Link>
        )}
      </div>
      {memberships.isSuccess && (!allowed || accessLost) && <AccessLost />}
      {roles.isPending && allowed && <p className="text-muted-foreground">Loading roles…</p>}
      {roles.isError && !accessLost && <FormAlert>{errorMessage(roles.error, "We couldn't load roles.")}</FormAlert>}
      <p className="text-sm text-muted-foreground">
        A member's permissions are everything their roles allow, plus the Member role, which everyone has. You can
        only grant or remove permissions you hold yourself.
      </p>
      <ul className="flex flex-col gap-2">
        {roles.data?.map((role) => (
          <li key={role.id}>
            <Link
              to={`/club/roles/${role.id}`}
              className={cn(ROW, "min-h-12 outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}
            >
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="flex items-center gap-1 font-semibold">
                  {role.key === "admin" && <Lock aria-hidden className="size-4 text-muted-foreground" />}
                  {role.name}
                </span>
                <span className="text-sm text-muted-foreground">
                  {role.key === "member"
                    ? "Everyone in the club"
                    : `${role.member_count} ${role.member_count === 1 ? "member" : "members"}`}{" "}
                  · {role.key === "admin" ? "every permission" : `${role.permissions.length} ${role.permissions.length === 1 ? "permission" : "permissions"}`}
                </span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
