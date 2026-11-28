import { useId, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search, UserCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FieldError, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { askPlayerForGuest, guestKeys } from "@/lib/guests"
import { MIN_SEARCH_LENGTH, playerKeys, searchPlayers } from "@/lib/profile"

/**
 * The guest has since joined Coast TT: find them in the player directory and ask whether they are this
 * guest (REQ-003). They accept or decline in the app, and nothing moves until they accept. Names are
 * never matched for them: staff choose, the player confirms.
 */
export function AskPlayer({ orgId, guestId, guestName, onDone }: { orgId: string; guestId: string; guestName: string; onDone: () => void }) {
  const id = useId()
  const queryClient = useQueryClient()
  const [input, setInput] = useState(guestName)
  const [term, setTerm] = useState(guestName.trim())
  const results = useQuery({ queryKey: playerKeys.search(term), queryFn: () => searchPlayers(term), enabled: term.length >= MIN_SEARCH_LENGTH })
  const ask = useMutation({
    mutationFn: (playerId: string) => askPlayerForGuest(orgId, guestId, playerId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: guestKeys.all })
      onDone()
    },
  })
  const found = results.data?.results ?? []

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="flex basis-full flex-col gap-2">
      <p className="text-sm text-muted-foreground">
        Already on Coast TT? Find them in the player directory. They're asked in the app whether they played as “{guestName}”, and their entries and matches move only if they say yes.
      </p>
      <form onSubmit={onSearch} className="flex gap-2">
        <label htmlFor={id} className="sr-only">
          Find a player by name
        </label>
        <Input id={id} type="search" placeholder="Find a player by name" maxLength={80} value={input} onChange={(e) => setInput(e.target.value)} />
        <Button type="submit" variant="outline" size="icon" aria-label="Find player">
          <Search aria-hidden className="size-5" />
        </Button>
      </form>
      <div aria-live="polite" className="flex flex-col gap-2">
        {term.length > 0 && term.length < MIN_SEARCH_LENGTH && <p className="text-sm text-muted-foreground">Type at least {MIN_SEARCH_LENGTH} characters.</p>}
        {results.isLoading && <p className="text-sm text-muted-foreground">Searching…</p>}
        {results.isError && <FieldError>Search isn't working right now.</FieldError>}
        {results.isSuccess && found.length === 0 && (
          <p className="text-sm text-muted-foreground">No listed player matches “{term}”. Invite them by email or phone, or make a new link to share.</p>
        )}
        {ask.isError && <FormAlert>{errorMessage(ask.error, "We couldn't ask that player.")}</FormAlert>}
        {found.length > 0 && (
          <ul className="flex flex-col gap-2" aria-label="Players found">
            {found.slice(0, 8).map((player) => (
              <li key={player.id} className="flex min-h-12 items-center justify-between gap-2 rounded-lg border bg-card py-1 pr-1 pl-3">
                <span className="min-w-0 break-words">
                  {player.display_name}
                  {player.clubs.length > 0 && <span className="text-muted-foreground"> · {player.clubs.join(", ")}</span>}
                </span>
                <Button
                  type="button"
                  size="sm"
                  className="shrink-0"
                  aria-label={`Ask ${player.display_name} whether they are ${guestName}`}
                  disabled={ask.isPending}
                  onClick={() => ask.mutate(player.id)}
                >
                  <UserCheck aria-hidden className="size-4" /> Ask
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
