import type { ReactNode } from "react"
import { Building2, MapPin, UsersRound } from "lucide-react"
import type { Organization } from "@/lib/clubs"
import { OrganizationName } from "@/components/clubs/KindBadge"
import { countryName } from "@/lib/geography"

/** One organization as a list row: icon, name, town and kind, plus an optional action on the right. */
export function OrganizationCard({ organization, children }: { organization: Organization; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4">
      <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-surface-selected">
        {organization.kind === "team" ? <UsersRound aria-hidden className="size-6 text-brand-blue" /> : <Building2 aria-hidden className="size-6 text-brand-blue" />}
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <OrganizationName organization={organization} className="font-semibold" />
        <span className="flex items-center gap-1 text-sm text-muted-foreground">
          <MapPin aria-hidden className="size-3.5" />
          {[...new Set([organization.town, organization.region, countryName(organization.country)])].filter(Boolean).join(", ")}
        </span>
      </div>
      {children}
    </div>
  )
}
