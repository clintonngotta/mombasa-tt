import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Check, Clock, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { OrganizationCard } from "@/components/clubs/OrganizationCard"
import { errorMessage } from "@/lib/api"
import { clubKeys, listMyJoinRequests, useMemberships } from "@/lib/clubs"
import { requestToJoin, searchOrganizations } from "@/lib/onboarding"

export function FindClubPage() {
  const queryClient = useQueryClient()
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")

  const results = useQuery({
    queryKey: ["organizations", "search", term],
    queryFn: () => searchOrganizations(term),
    enabled: term.length >= 2,
  })
  const memberships = useMemberships()
  const myRequests = useQuery({ queryKey: clubKeys.myJoinRequests, queryFn: listMyJoinRequests })
  const join = useMutation({
    mutationFn: requestToJoin,
    onSettled: () => queryClient.invalidateQueries({ queryKey: clubKeys.myJoinRequests }),
  })

  const memberOf = new Set(memberships.data?.results.map((m) => m.organization.id))
  const pending = new Set(myRequests.data?.results.filter((r) => r.status === "pending").map((r) => r.organization))

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="flex max-w-[640px] flex-col gap-6">
      <Link to="/club" className="flex items-center gap-1 self-start text-sm font-semibold text-muted-foreground hover:text-foreground">
        <ArrowLeft aria-hidden className="size-4" /> Club
      </Link>
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Find a club</h1>
        <p className="text-muted-foreground">Search by name or town. Club staff approve join requests.</p>
      </div>

      <form role="search" onSubmit={onSearch} className="flex gap-2">
        <label htmlFor="find-club" className="sr-only">
          Club name or town
        </label>
        <Input
          id="find-club"
          type="search"
          placeholder="Club name or town, e.g. Mombasa"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <Button type="submit" size="icon" aria-label="Search">
          <Search aria-hidden className="size-5" />
        </Button>
      </form>

      <section aria-live="polite" className="flex flex-col gap-3">
        {term.length > 0 && term.length < 2 && <p className="text-muted-foreground">Type at least two characters.</p>}
        {results.isLoading && <p className="text-muted-foreground">Searching…</p>}
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now.")}</FormAlert>}
        {results.data?.results.length === 0 && (
          <p className="text-muted-foreground">
            Nothing matches “{term}”. Try a town name, or <Link to="/club/new" className="font-semibold text-brand-blue underline">register your club</Link>.
          </p>
        )}
        {join.isError && <FormAlert>{errorMessage(join.error, "We couldn't send that join request.")}</FormAlert>}

        <ul className="flex flex-col gap-3">
          {results.data?.results.map((club) => (
            <li key={club.id}>
              <OrganizationCard organization={club}>
                {memberOf.has(club.id) ? (
                  <span className="flex items-center gap-1 text-sm font-semibold text-success">
                    <Check aria-hidden className="size-4" /> Member
                  </span>
                ) : pending.has(club.id) ? (
                  <span className="flex items-center gap-1 text-sm font-semibold text-warning">
                    <Clock aria-hidden className="size-4" /> Pending
                  </span>
                ) : (
                  <Button
                    variant="outline"
                    disabled={join.isPending && join.variables === club.id}
                    onClick={() => join.mutate(club.id)}
                  >
                    Request to join
                  </Button>
                )}
              </OrganizationCard>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
