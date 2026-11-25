import { useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Search, Warehouse } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { LocationFields } from "@/components/forms/LocationFields"
import { OpenBadge } from "@/components/facilities/OpenBadge"
import { FinderTabs, NearMeControls } from "@/components/places/NearMe"
import { errorMessage } from "@/lib/api"
import { ROW } from "@/lib/clubAdmin"
import { facilityKeys, findFacilities, type Facility, type FacilitySearch } from "@/lib/facilities"
import { findFacilitiesNear, formatDistance, useNearMe } from "@/lib/nearby"
import { cn } from "@/lib/utils"

const DEFAULT_COUNTRY = "KE"
const NO_AREA = { country: "", region: "", city: "" }

function filtersFrom(params: URLSearchParams): FacilitySearch {
  return {
    name: params.get("name") ?? "",
    country: params.get("country") ?? "",
    region: params.get("region") ?? "",
    city: params.get("city") ?? "",
    openNow: params.get("open") === "1",
  }
}

/** Find a place to play (REQ-044): facility branches by name or city, by region, or by distance from
 * where you are, and which are open now. */
export function FindFacilityPage() {
  const [params, setParams] = useSearchParams()
  const applied = filtersFrom(params)
  const [draft, setDraft] = useState<FacilitySearch>({ ...applied, country: applied.country || DEFAULT_COUNTRY })
  const [byArea, setByArea] = useState(!!applied.region || !!applied.city)
  const near = useNearMe()

  const list = useQuery({ queryKey: facilityKeys.find(applied), queryFn: () => findFacilities(applied), enabled: !near.position })
  // Keyed by a counter, never by the coordinates, and never saved on the device (lib/offline).
  const nearby = useQuery({
    queryKey: ["nearby", "facilities", near.stamp, near.radius, applied.name, applied.openNow],
    queryFn: () => findFacilitiesNear(near.position!, near.radius, applied.name, applied.openNow),
    enabled: !!near.position,
    gcTime: 0,
  })
  const results = near.position ? nearby : list
  const facilities: (Facility & { distance_m?: number })[] = results.data?.results ?? []
  const count = results.data?.count ?? 0

  function apply(next: FacilitySearch) {
    const query = new URLSearchParams()
    const { openNow, ...rest } = { ...(byArea ? next : { ...next, ...NO_AREA }), name: next.name.trim() }
    for (const [key, value] of Object.entries(rest)) if (value) query.set(key, value)
    if (openNow) query.set("open", "1")
    setParams(query, { replace: true })
  }

  function onSearch(e: FormEvent) {
    e.preventDefault()
    apply(draft)
  }

  function onClear() {
    setDraft({ name: "", country: DEFAULT_COUNTRY, region: "", city: "", openNow: false })
    setByArea(false)
    near.stop()
    setParams({}, { replace: true })
  }

  const filtered = !!applied.name || !!applied.region || !!applied.city || applied.openNow || !!near.position
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/play">Play</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Find a place to play</h1>
        <p className="text-muted-foreground">Halls and facilities with tables: type a name or a city, or see the ones near you, with their hours and what a visit includes.</p>
      </div>
      <FinderTabs current="facilities" />

      <form role="search" noValidate onSubmit={onSearch} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
        <Field
          label="Name, city or town"
          type="search"
          maxLength={120}
          placeholder="e.g. Tononoka Hall, or Mombasa"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        {byArea && !near.position && <LocationFields value={draft} onChange={(location) => setDraft({ ...draft, ...location })} />}
        <label className="flex min-h-12 items-center gap-3 font-semibold">
          <input
            type="checkbox"
            className="size-5 accent-brand-blue"
            checked={draft.openNow}
            onChange={(e) => {
              // Applies straight away: it is a switch on the list, not something to type.
              const next = { ...draft, openNow: e.target.checked }
              setDraft(next)
              apply(next)
            }}
          />
          Open now
        </label>
        <div className="flex flex-wrap gap-2">
          <Button type="submit">
            <Search aria-hidden className="size-4" /> Search
          </Button>
          {!near.position && (
            <Button type="button" variant="ghost" aria-expanded={byArea} onClick={() => setByArea(!byArea)}>
              {byArea ? "Hide region and city" : "Choose a region or city"}
            </Button>
          )}
          {filtered && (
            <Button type="button" variant="ghost" onClick={onClear}>
              Clear
            </Button>
          )}
        </div>
        <NearMeControls near={near} what="Places to play" />
      </form>

      <section aria-live="polite" aria-label="Facilities found" className="flex flex-col gap-3">
        {results.isFetching && !results.data && <p className="text-muted-foreground">Searching…</p>}
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now.")}</FormAlert>}
        {results.isSuccess && facilities.length === 0 && (
          <p className="text-muted-foreground">
            {near.position
              ? `No place to play has a map location within ${formatDistance(near.radius)} of you${applied.openNow ? " and is open now" : ""}. Try a wider distance or search by city.`
              : `No facility matches. Try a shorter name or another city${applied.openNow ? ", or include those closed now" : ""}.`}
          </p>
        )}
        {results.isSuccess && facilities.length > 0 && (near.position || count > facilities.length) && (
          <p className="text-sm text-muted-foreground">
            {count > facilities.length
              ? `Showing ${near.position ? "the nearest " : ""}${facilities.length} of ${count}. ${near.position ? "Choose a shorter distance" : "Add a city or more of the name"} to narrow the list.`
              : `${facilities.length} within ${formatDistance(near.radius)}, nearest first`}
          </p>
        )}
        <ul className="flex flex-col gap-2">
          {results.isSuccess &&
            facilities.map((facility) => (
              <li key={facility.id}>
                <Link to={`/facilities/${facility.id}`} className={cn(ROW, "outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50")}>
                  <Warehouse aria-hidden className="size-6 text-brand-blue" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-semibold">{facility.name}</span>
                    <span className="text-sm text-muted-foreground">
                      {facility.organization_name} · {[facility.town, facility.region].filter(Boolean).join(", ")}
                    </span>
                    <span className="text-sm text-muted-foreground">
                      {facility.distance_m !== undefined && <span className="font-semibold text-brand-blue">{formatDistance(facility.distance_m)} away · </span>}
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
