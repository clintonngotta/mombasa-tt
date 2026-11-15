import { useId } from "react"
import { ChevronsUpDown } from "lucide-react"
import { setActiveOrganization, useActiveMembership } from "@/lib/clubs"
import { cn } from "@/lib/utils"

/** Chooses which organization the Club tab acts for. Hidden until the player belongs to one. */
export function OrganizationSwitcher({ className }: { className?: string }) {
  const id = useId()
  const { all, active } = useActiveMembership()
  if (!active) return null

  if (all.length === 1) {
    return <span className={cn("truncate text-sm font-semibold text-muted-foreground", className)}>{active.organization.name}</span>
  }

  return (
    <div className={cn("relative", className)}>
      <label htmlFor={id} className="sr-only">
        Active organization
      </label>
      <select
        id={id}
        value={active.organization.id}
        onChange={(e) => setActiveOrganization(e.target.value)}
        className="h-12 w-full appearance-none truncate rounded-lg border bg-card pr-9 pl-3 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {all.map((m) => (
          <option key={m.organization.id} value={m.organization.id}>
            {m.organization.name}
          </option>
        ))}
      </select>
      <ChevronsUpDown aria-hidden className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  )
}
