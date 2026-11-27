import { SearchSelect } from "@/components/forms/SelectField"
import { KindBadge, OrganizationName } from "@/components/clubs/KindBadge"
import { setActiveOrganization, useActiveMembership } from "@/lib/clubs"
import { cn } from "@/lib/utils"

/** Chooses which organization the Club tab acts for. Hidden until the player belongs to one. */
export function OrganizationSwitcher({ className }: { className?: string }) {
  const { all, active } = useActiveMembership()
  if (!active) return null

  if (all.length === 1) {
    return <OrganizationName organization={active.organization} className={cn("text-sm font-semibold text-muted-foreground", className)} />
  }

  return (
    <SearchSelect
      aria-label="Active organization"
      value={active.organization.id}
      onChange={setActiveOrganization}
      className={cn("text-sm font-semibold", className)}
      options={all.map(({ organization }) => ({ value: organization.id, label: organization.name, badge: <KindBadge kind={organization.kind} /> }))}
    />
  )
}
