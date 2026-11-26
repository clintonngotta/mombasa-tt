import { useState, type FormEvent } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { BackLink } from "@/components/layout/BackLink"
import { Button, buttonVariants } from "@/components/ui/button"
import { Field, FormAlert } from "@/components/forms/Field"
import { LocationFields } from "@/components/forms/LocationFields"
import { OrganizationCard } from "@/components/clubs/OrganizationCard"
import { JoinStatus } from "@/components/clubs/JoinStatus"
import { FinderTabs, NearMeControls } from "@/components/places/NearMe"
import { errorMessage } from "@/lib/api"
import { clubKeys, findClubs, requestToJoin, useJoinState, type ClubSearch, type Organization } from "@/lib/clubs"
import { findClubsNear, formatDistance, useNearMe } from "@/lib/nearby"

const DEFAULT_COUNTRY = "KE"
const NO_AREA = { country: "", region: "", city: "" }

function filtersFrom(params: URLSearchParams): ClubSearch {
  return {
    name: params.get("name") ?? "",
    country: params.get("country") ?? "",
    region: params.get("region") ?? "",
    city: params.get("city") ?? "",
  }
}

/** A search is worth sending once it has two letters to match, or picks an area. */
const searchable = (f: ClubSearch) => f.name.trim().length >= 2 || !!f.region || !!f.city

/** Find clubs by name or city, by region, or by distance from where you are; open one to see its
 * details, and ask to join (REQ-004). */
export function FindClubPage() {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const applied = filtersFrom(params)
  const [draft, setDraft] = useState<ClubSearch>({ ...applied, country: applied.country || DEFAULT_COUNTRY })
  // The country, region and city pickers stay folded away until someone wants them.
  const [byArea, setByArea] = useState(!!applied.region || !!applied.city)
  const [tooShort, setTooShort] = useState(false)
  const near = useNearMe()
  const listed = !near.position && params.has("searched") && searchable(applied)

  const list = useQuery({ queryKey: clubKeys.find(applied), queryFn: () => findClubs(applied), enabled: listed })
  // Keyed by a counter, never by the coordinates, and never saved on the device (lib/offline).
  const nearby = useQuery({
    queryKey: ["nearby", "clubs", near.stamp, near.radius, applied.name],
    queryFn: () => findClubsNear(near.position!, near.radius, applied.name),
    enabled: !!near.position,
    gcTime: 0,
  })
  const results = near.position ? nearby : list
  const joinState = useJoinState()
  const join = useMutation({
    mutationFn: requestToJoin,
    // Also on error: a 409 already_member means our membership list is out of date.
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })

  function onSearch(e: FormEvent) {
    e.preventDefault()
    const next = { ...(byArea ? draft : { ...draft, ...NO_AREA }), name: draft.name.trim() }
    // Near me, the name only narrows the list, so an empty one is fine.
    const ok = near.position ? true : searchable(next)
    setTooShort(!ok)
    if (!ok) return
    const query = new URLSearchParams({ searched: "1" })
    for (const [key, value] of Object.entries(next)) if (value) query.set(key, value)
    setParams(query, { replace: true })
  }

  function onClear() {
    setDraft({ name: "", country: DEFAULT_COUNTRY, region: "", city: "" })
    setByArea(false)
    setTooShort(false)
    near.stop()
    setParams({}, { replace: true })
  }

  const clubs: (Organization & { distance_m?: number })[] = results.data?.results ?? []
  const count = results.data?.count ?? 0
  const shown = near.position ? nearby.isSuccess : list.isSuccess && listed
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Find a club</h1>
        <p className="text-muted-foreground">Type a club name or a city, or see the clubs near you. Open a club to see where it plays and when it trains, then ask to join.</p>
      </div>
      <FinderTabs current="clubs" />

      <form role="search" noValidate onSubmit={onSearch} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
        <Field
          label="Club name, city or town"
          type="search"
          maxLength={120}
          placeholder="e.g. Coast Spinners, or Mombasa"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        {byArea && !near.position && <LocationFields value={draft} onChange={(location) => setDraft({ ...draft, ...location })} />}
        {tooShort && <FormAlert>Type at least two letters of a club name or city{byArea ? ", or choose a region or city" : ""}.</FormAlert>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit">
            <Search aria-hidden className="size-4" /> Search
          </Button>
          {!near.position && (
            <Button type="button" variant="ghost" aria-expanded={byArea} onClick={() => setByArea(!byArea)}>
              {byArea ? "Hide region and city" : "Choose a region or city"}
            </Button>
          )}
          {(params.has("searched") || near.position) && (
            <Button type="button" variant="ghost" onClick={onClear}>
              Clear
            </Button>
          )}
        </div>
        <NearMeControls near={near} what="Clubs" />
      </form>

      <section aria-live="polite" aria-label="Clubs found" className="flex flex-col gap-3">
        {results.isFetching && !results.data && <p className="text-muted-foreground">Searching…</p>}
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now.")}</FormAlert>}
        {shown && clubs.length === 0 && (
          <p className="text-muted-foreground">
            {near.position
              ? `No club has a map location within ${formatDistance(near.radius)} of you. Try a wider distance or search by city: clubs that haven't set their map location only show in a city search. Or `
              : "No clubs match. Try a shorter name or another city, or "}
            <Link to="/club/new" className="font-semibold text-brand-blue underline">
              register your club
            </Link>
            .
          </p>
        )}
        {shown && clubs.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {count === clubs.length
              ? `${clubs.length} ${clubs.length === 1 ? "club" : "clubs"}${near.position ? `, nearest first` : ""}`
              : `Showing ${near.position ? "the nearest " : ""}${clubs.length} of ${count} clubs. ${near.position ? "Choose a shorter distance" : "Add a city or more of the name"} to narrow the list.`}
          </p>
        )}
        {joinState.failed && <FormAlert>We couldn't check which clubs you've joined, so join requests are paused. Try again shortly.</FormAlert>}
        {join.isError && <FormAlert>{errorMessage(join.error, "We couldn't send that join request.")}</FormAlert>}

        <ul className="flex flex-col gap-3">
          {shown &&
            clubs.map((club) => (
              <li key={club.id}>
                <OrganizationCard organization={club}>
                  <div className="flex flex-wrap items-center gap-2">
                    {club.distance_m !== undefined && <span className="text-sm font-semibold text-brand-blue">{formatDistance(club.distance_m)} away</span>}
                    <Link to={`/club/find/${club.id}`} state={{ from: `/club/find?${params}` }} className={buttonVariants({ variant: "ghost" })} aria-label={`Details of ${club.name}`}>
                      Details
                    </Link>
                    <JoinStatus state={joinState.of(club.id)} name={club.name} busy={join.isPending && join.variables === club.id} onJoin={() => join.mutate(club.id)} />
                  </div>
                  {club.description && <p className="line-clamp-2 basis-full text-sm text-muted-foreground">{club.description}</p>}
                </OrganizationCard>
              </li>
            ))}
        </ul>
      </section>
    </div>
  )
}
