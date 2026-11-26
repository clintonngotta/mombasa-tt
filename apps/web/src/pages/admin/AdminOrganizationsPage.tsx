import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { Building2, ChevronRight, GraduationCap, Landmark, Map, Users } from "lucide-react"
import { FormAlert } from "@/components/forms/Field"
import { SearchSelect } from "@/components/forms/SelectField"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { KIND_LABEL, setActiveOrganization, type OrganizationKind } from "@/lib/clubs"
import { countryName } from "@/lib/geography"
import { dayLabel, listOrganizations, platformKeys } from "@/lib/platform"
import { cn } from "@/lib/utils"
import { Pager, SearchBox } from "@/pages/admin/BackOffice"

const ICON = { club: Users, facility: Building2, club_facility: Building2, regional_body: Map, national_body: Landmark, coaching: GraduationCap } as const
const KINDS = [{ value: "all", label: "Every kind" }, ...Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))]

/** Every club, facility, governing body and coaching desk. Opening one shows it as its members see it,
 * with the platform's authority to change it (its place, its admin). */
export function AdminOrganizationsPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const [kind, setKind] = useState("all")
  const [page, setPage] = useState(1)
  const organizations = useQuery({
    queryKey: platformKeys.organizations(search, kind, page),
    queryFn: () => listOrganizations(search, kind, page),
    placeholderData: keepPreviousData,
  })

  function open(id: string) {
    setActiveOrganization(id)
    navigate("/club")
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox label="Find an organization" placeholder="Name, town or region" onSearch={(term) => { setSearch(term); setPage(1) }} />
        <SearchSelect aria-label="Kind of organization" className="w-52" options={KINDS} value={kind} onChange={(value) => { setKind(value); setPage(1) }} />
      </div>
      <section aria-live="polite" className="flex flex-col gap-3">
        {organizations.isPending && <p className="text-muted-foreground">Loading…</p>}
        {organizations.isError && <FormAlert>{errorMessage(organizations.error, "We couldn't load the organizations.")}</FormAlert>}
        {organizations.isSuccess && (
          <p className="text-sm text-muted-foreground">
            {organizations.data.count.toLocaleString("en-KE")} {organizations.data.count === 1 ? "organization" : "organizations"}
            {search && ` matching “${search}”`}
          </p>
        )}
        <ul className="flex flex-col gap-2">
          {(organizations.data?.results ?? []).map((organization) => {
            const Icon = ICON[organization.kind as OrganizationKind] ?? Users
            const place = [organization.town, organization.region, organization.country && countryName(organization.country)].filter(Boolean).join(", ")
            return (
              <li key={organization.id}>
                <button type="button" onClick={() => open(organization.id)} className={cn(ROW, "w-full min-h-12 text-left outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50")}>
                  <Icon aria-hidden className="size-5 shrink-0 text-brand-blue" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="font-semibold break-words">{organization.name}</span>
                    <span className="text-sm text-muted-foreground">
                      {KIND_LABEL[organization.kind as OrganizationKind]} · {place}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {organization.admin_name ? `Admin: ${organization.admin_name}` : "No admin"} · {organization.members} {organization.members === 1 ? "member" : "members"} · since{" "}
                      {dayLabel(organization.created_at)}
                    </span>
                  </span>
                  <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
                </button>
              </li>
            )
          })}
        </ul>
      </section>
      {organizations.isSuccess && <Pager page={page} count={organizations.data.count} onPage={setPage} />}
    </div>
  )
}
