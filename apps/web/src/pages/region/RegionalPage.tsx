import { useNavigate } from "react-router-dom"
import { Building2, ChevronRight, ClipboardCheck, Map, Users } from "lucide-react"
import { OrgLinkRow } from "@/components/clubs/OrganizationLinks"
import { Approvals } from "@/pages/region/RegionPage"
import { ROW } from "@/lib/clubAdmin"
import { KIND_LABEL, setActiveOrganization, useActiveMembership, type Membership } from "@/lib/clubs"
import { isOfficial } from "@/lib/navigation"
import { cn } from "@/lib/utils"

const AUTHORITY_LABEL = { platform: "Platform super admin", country: "Country official", regional: "Regional official" } as const

/** A regional or country official's own page (REQ-048, geographic authority): the tournaments waiting for
 * their approval, their regional body, and the clubs and facilities they oversee. Officials are players too,
 * so their personal pages stay in the menu beside this one. */
export function RegionalPage() {
  const navigate = useNavigate()
  const { memberships, all } = useActiveMembership()
  const overseen = all.filter((m) => m.authority)
  const bodies = all.filter((m) => m.organization.kind === "regional_body" && !m.managedOnly)
  const authority = overseen[0]?.authority
  const platform = overseen.some((m) => m.authority === "platform")

  function open(membership: Membership, to: string) {
    setActiveOrganization(membership.organization.id)
    navigate(to)
  }

  if (memberships.isPending) return <p className="text-muted-foreground">Loading…</p>
  if (!isOfficial(all)) {
    return <p className="max-w-[640px] text-muted-foreground">This page is for regional and country officials and regional bodies.</p>
  }

  return (
    <div className="flex max-w-[860px] flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Regional</h1>
        <p className="text-muted-foreground">
          {authority ? AUTHORITY_LABEL[authority] : "Regional body"}
          {overseen.length > 0 && ` · overseeing ${overseen.length} ${overseen.length === 1 ? "organization" : "organizations"}`}
        </p>
      </div>

      {bodies.length > 0 && (
        <section aria-labelledby="bodies-heading" className="flex flex-col gap-2">
          <h2 id="bodies-heading" className="text-xl font-bold">
            Your regional body
          </h2>
          {bodies.map((body) => (
            <button key={body.id} type="button" onClick={() => open(body, "/region")} className={cn(ROW, "min-h-12 text-left font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
              <Map aria-hidden className="size-5 text-brand-blue" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate">{body.organization.name}</span>
                <span className="text-sm font-normal text-muted-foreground">Agenda, clubs, articles, meetings and sponsorships</span>
              </span>
              <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
            </button>
          ))}
        </section>
      )}

      <section aria-labelledby="approvals-heading" className="flex flex-col gap-3">
        <h2 id="approvals-heading" className="text-xl font-bold">
          Waiting for your approval
        </h2>
        <Approvals />
        {platform && (
          <OrgLinkRow to="/events/review" icon={<ClipboardCheck aria-hidden className="size-5 text-brand-blue" />}>
            Events listed from elsewhere, waiting for review
          </OrgLinkRow>
        )}
      </section>

      {overseen.length > 0 && (
        <section aria-labelledby="overseen-heading" className="flex flex-col gap-3">
          <h2 id="overseen-heading" className="text-xl font-bold">
            Clubs and facilities you oversee
          </h2>
          <p className="text-sm text-muted-foreground">You read them as their members do. Running them stays with each club's own admin.</p>
          <ul className="flex flex-col gap-2">
            {overseen.map((membership) => {
              const Icon = membership.organization.kind === "club" ? Users : Building2
              return (
                <li key={membership.id}>
                  <button type="button" onClick={() => open(membership, "/club")} className={cn(ROW, "w-full min-h-12 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                    <Icon aria-hidden className="size-5 shrink-0 text-brand-blue" />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate font-semibold">{membership.organization.name}</span>
                      <span className="text-sm text-muted-foreground">
                        {KIND_LABEL[membership.organization.kind]}
                        {membership.organization.town && ` · ${membership.organization.town}`}
                      </span>
                    </span>
                    <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
