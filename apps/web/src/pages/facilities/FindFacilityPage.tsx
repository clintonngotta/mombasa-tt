import { useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Search, Warehouse } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { LocationFields } from "@/components/forms/LocationFields"
import { OpenBadge } from "@/components/facilities/OpenBadge"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { facilityKeys, findFacilities, type FacilitySearch } from "@/lib/facilities"
import { cn } from "@/lib/utils"

const DEFAULT_COUNTRY = "KE"

function filtersFrom(params: URLSearchParams): FacilitySearch {
  return {
    name: params.get("name") ?? "",
    country: params.get("country") ?? DEFAULT_COUNTRY,
    region: params.get("region") ?? "",
    city: params.get("city") ?? "",
    openNow: params.get("open") === "1",
  }
}

/** Find a place to play (REQ-044): facility branches by place and name, and which are open now. */
export function FindFacilityPage() {
  const [params, setParams] = useSearchParams()
  const applied = filtersFrom(params)
  const [draft, setDraft] = useState<FacilitySearch>(applied)
  const results = useQuery({ queryKey: facilityKeys.find(applied), queryFn: () => findFacilities(applied) })
  const facilities = results.data?.results ?? []

  function onSearch(e: FormEvent) {
    e.preventDefault()
    const query = new URLSearchParams()
    const { openNow, ...rest } = { ...draft, name: draft.name.trim() }
    for (const [key, value] of Object.entries(rest)) if (value) query.set(key, value)
    if (openNow) query.set("open", "1")
    setParams(query, { replace: true })
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/play">Play</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Find a place to play</h1>
        <p className="text-muted-foreground">Halls and facilities with tables to play on: where they are, their hours and what a visit includes.</p>
      </div>

      <form role="search" noValidate onSubmit={onSearch} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
        <Field label="Name" optional type="search" maxLength={120} placeholder="Facility or hall" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <LocationFields value={draft} onChange={(location) => setDraft({ ...draft, ...location })} />
        <label className="flex min-h-12 items-center gap-3 font-semibold">
          <input type="checkbox" className="size-5 accent-brand-blue" checked={draft.openNow} onChange={(e) => setDraft({ ...draft, openNow: e.target.checked })} />
          Open now
        </label>
        <Button type="submit" className="self-start">
          <Search aria-hidden className="size-4" /> Find
        </Button>
      </form>

      <section aria-live="polite" aria-label="Facilities found" className="flex flex-col gap-3">
        {results.isLoading && <p className="text-muted-foreground">Searching…</p>}
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now.")}</FormAlert>}
        {results.isSuccess && facilities.length === 0 && <p className="text-muted-foreground">No facility matches. Try a wider area{applied.openNow ? ", or include those closed now" : ""}.</p>}
        {results.isSuccess && results.data.count > facilities.length && (
          <p className="text-sm text-muted-foreground">
            Showing {facilities.length} of {results.data.count}. Narrow the area to see the rest.
          </p>
        )}
        <ul className="flex flex-col gap-2">
          {facilities.map((facility) => (
            <li key={facility.id}>
              <Link to={`/facilities/${facility.id}`} className={cn(ROW, "outline-none focus-visible:ring-3 focus-visible:ring-ring/50")}>
                <Warehouse aria-hidden className="size-6 text-brand-blue" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold">{facility.name}</span>
                  <span className="text-sm text-muted-foreground">
                    {facility.organization_name} · {[facility.town, facility.region].filter(Boolean).join(", ")}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {facility.match_tables} match {facility.match_tables === 1 ? "table" : "tables"}
                    {facility.training_tables > 0 && ` · ${facility.training_tables} for training`}
                  </span>
                </span>
                <OpenBadge open={facility.open_now} />
                <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
