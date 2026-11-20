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
import { errorMessage } from "@/lib/api"
import { clubKeys, findClubs, requestToJoin, useJoinState, type ClubSearch } from "@/lib/clubs"

const DEFAULT_COUNTRY = "KE"

function filtersFrom(params: URLSearchParams): ClubSearch {
  return {
    name: params.get("name") ?? "",
    country: params.get("country") ?? DEFAULT_COUNTRY,
    region: params.get("region") ?? "",
    city: params.get("city") ?? "",
  }
}

/** A search is worth sending once it names a club (two letters or more) or picks an area. */
const searchable = (f: ClubSearch) => f.name.trim().length >= 2 || !!f.region || !!f.city

/** Find clubs by name, region or city, open one to see its details, and ask to join (REQ-004). */
export function FindClubPage() {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const applied = filtersFrom(params)
  const [draft, setDraft] = useState<ClubSearch>(applied)
  const [tooShort, setTooShort] = useState(false)
  const active = params.has("searched") && searchable(applied)

  const results = useQuery({ queryKey: clubKeys.find(applied), queryFn: () => findClubs(applied), enabled: active })
  const joinState = useJoinState()
  const join = useMutation({
    mutationFn: requestToJoin,
    // Also on error: a 409 already_member means our membership list is out of date.
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.all }),
  })

  function onSearch(e: FormEvent) {
    e.preventDefault()
    const next = { ...draft, name: draft.name.trim() }
    setTooShort(!searchable(next))
    if (!searchable(next)) return
    const query = new URLSearchParams({ searched: "1" })
    for (const [key, value] of Object.entries(next)) if (value) query.set(key, value)
    setParams(query, { replace: true })
  }

  function onClear() {
    setDraft({ name: "", country: DEFAULT_COUNTRY, region: "", city: "" })
    setTooShort(false)
    setParams({}, { replace: true })
  }

  const clubs = results.data?.results ?? []
  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <BackLink to="/club">Club</BackLink>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Find a club</h1>
        <p className="text-muted-foreground">
          Search by club name, or choose a region or city to see every club there. Open a club to see where it plays, when it trains and its coming tournaments.
        </p>
      </div>

      <form role="search" noValidate onSubmit={onSearch} className="flex flex-col gap-4 rounded-xl border bg-card p-4">
        <Field
          label="Club name"
          optional
          type="search"
          maxLength={120}
          placeholder="e.g. Coast Spinners"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        <LocationFields value={draft} onChange={(location) => setDraft({ ...draft, ...location })} />
        {tooShort && <FormAlert>Type at least two letters of a club name, or choose a region or city.</FormAlert>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit">
            <Search aria-hidden className="size-4" /> Find clubs
          </Button>
          {params.has("searched") && (
            <Button type="button" variant="ghost" onClick={onClear}>
              Clear
            </Button>
          )}
        </div>
      </form>

      <section aria-live="polite" aria-label="Clubs found" className="flex flex-col gap-3">
        {results.isLoading && <p className="text-muted-foreground">Searching…</p>}
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now.")}</FormAlert>}
        {results.isSuccess && clubs.length === 0 && (
          <p className="text-muted-foreground">
            No clubs match. Try a wider area, or{" "}
            <Link to="/club/new" className="font-semibold text-brand-blue underline">
              register your club
            </Link>
            .
          </p>
        )}
        {results.isSuccess && clubs.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {results.data.count === clubs.length ? `${clubs.length} ${clubs.length === 1 ? "club" : "clubs"}` : `Showing ${clubs.length} of ${results.data.count} clubs. Narrow the area to see the rest.`}
          </p>
        )}
        {joinState.failed && <FormAlert>We couldn't check which clubs you've joined, so join requests are paused. Try again shortly.</FormAlert>}
        {join.isError && <FormAlert>{errorMessage(join.error, "We couldn't send that join request.")}</FormAlert>}

        <ul className="flex flex-col gap-3">
          {clubs.map((club) => (
            <li key={club.id}>
              <OrganizationCard organization={club}>
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/club/find/${club.id}`} state={{ from: `/club/find?${params}` }} className={buttonVariants({ variant: "ghost" })} aria-label={`Details of ${club.name}`}>
                    Details
                  </Link>
                  <JoinStatus
                    state={joinState.of(club.id)}
                    name={club.name}
                    busy={join.isPending && join.variables === club.id}
                    onJoin={() => join.mutate(club.id)}
                  />
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
