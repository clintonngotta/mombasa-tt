import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Building2, Check, Clock, MapPin, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { OnboardingLayout } from "@/components/layout/OnboardingLayout"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { requestToJoin, saveDiscovery, searchOrganizations, useOnboardingDraft, type Organization } from "@/lib/onboarding"

const KIND_LABEL: Record<Organization["kind"], string> = {
  club: "Club",
  facility: "Facility",
  club_facility: "Club and facility",
}

export function FindCommunityPage() {
  const navigate = useNavigate()
  const [draft, updateDraft] = useOnboardingDraft()
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")

  const results = useQuery({
    queryKey: ["organizations", "search", term],
    queryFn: () => searchOrganizations(term),
    enabled: term.length >= 2,
  })

  const join = useMutation({
    mutationFn: (club: Organization) => requestToJoin(club.id),
    onSuccess: (_data, club) => updateDraft({ joinRequests: [...draft.joinRequests, club] }),
  })

  const save = useMutation({
    mutationFn: saveDiscovery,
    onSuccess: () => navigate("/onboarding/goals"),
  })

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  const requested = new Set(draft.joinRequests.map((c) => c.id))

  return (
    <OnboardingLayout
      step={2}
      backTo="/onboarding/profile"
      title="Find your community"
      description="Search for clubs and venues by name or town. Club staff approve join requests. You can enter public tournaments without joining the host club."
    >
      <form role="search" onSubmit={onSearch} className="flex gap-2">
        <label htmlFor="club-search" className="sr-only">
          Club name or town
        </label>
        <Input
          id="club-search"
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
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now. You can skip this and find a club later.")}</FormAlert>}
        {results.data?.results.length === 0 && (
          <p className="text-muted-foreground">No clubs or venues match “{term}”. Try a town name, or skip and look later from the Club tab.</p>
        )}
        {join.isError && <FormAlert>{errorMessage(join.error, "We couldn't send that join request. Try again.")}</FormAlert>}

        <ul className="flex flex-col gap-3">
          {results.data?.results.map((club) => {
            const isRequested = requested.has(club.id)
            const isSending = join.isPending && join.variables?.id === club.id
            return (
              <li key={club.id} className="flex items-center gap-3 rounded-xl border bg-card p-4">
                <span className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-surface-selected">
                  <Building2 aria-hidden className="size-6 text-brand-blue" />
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="font-semibold">{club.name}</span>
                  <span className="flex items-center gap-1 text-sm text-muted-foreground">
                    <MapPin aria-hidden className="size-3.5" />
                    {club.town} · {KIND_LABEL[club.kind]}
                  </span>
                </div>
                {isRequested ? (
                  <span className="flex items-center gap-1 text-sm font-semibold text-warning">
                    <Clock aria-hidden className="size-4" /> Pending
                  </span>
                ) : (
                  <Button variant="outline" disabled={isSending} onClick={() => join.mutate(club)}>
                    {isSending ? "Sending…" : "Request to join"}
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      </section>

      <label className="flex cursor-pointer items-start gap-3 rounded-xl border bg-card p-4 has-focus-visible:ring-3 has-focus-visible:ring-ring/50">
        <input
          type="checkbox"
          checked={draft.directoryOptIn}
          onChange={(e) => updateDraft({ directoryOptIn: e.target.checked })}
          className="peer sr-only"
        />
        <span
          aria-hidden
          className="mt-0.5 flex h-7 w-12 shrink-0 items-center rounded-full bg-border p-0.5 transition-colors peer-checked:bg-brand-blue peer-checked:[&>span]:translate-x-5"
        >
          <span className="size-6 rounded-full bg-white shadow transition-transform" />
        </span>
        <span className="flex flex-col">
          <span className="font-semibold">List me in the player directory</span>
          <span className="text-sm text-muted-foreground">
            Other players can find your name, clubs and rating. Your contact details and location are never shown. Off by default.
          </span>
        </span>
      </label>

      {save.isError && <FormAlert>{errorMessage(save.error)}</FormAlert>}
      <div className="flex flex-col gap-3">
        <Button size="lg" disabled={save.isPending} onClick={() => save.mutate(draft.directoryOptIn)}>
          {save.isPending ? "Saving…" : draft.joinRequests.length > 0 ? "Continue" : "Continue without joining"}
        </Button>
        {draft.joinRequests.length > 0 && (
          <p className="flex items-center justify-center gap-1.5 text-sm text-muted-foreground">
            <Check aria-hidden className="size-4 text-success" />
            {draft.joinRequests.length} join request{draft.joinRequests.length > 1 && "s"} sent
          </p>
        )}
      </div>
    </OnboardingLayout>
  )
}
