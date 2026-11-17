import { useId, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Plus, Search, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FieldError } from "@/components/forms/Field"
import { MIN_SEARCH_LENGTH, playerKeys, searchPlayers } from "@/lib/profile"

export type Picked = { id: string; display_name: string }

/**
 * Choose players for an entry from the player directory. `fixed` players (the person entering) are
 * shown and can't be removed. Only players who chose to be listed can be found.
 */
export function PlayerPicker({
  label,
  hint,
  picked,
  fixed = [],
  max,
  error,
  onChange,
}: {
  label: string
  hint?: string
  picked: Picked[]
  fixed?: Picked[]
  max: number
  error?: string
  onChange: (players: Picked[]) => void
}) {
  const id = useId()
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")
  const results = useQuery({ queryKey: playerKeys.search(term), queryFn: () => searchPlayers(term), enabled: term.length >= MIN_SEARCH_LENGTH })
  const chosen = new Set([...fixed, ...picked].map((player) => player.id))
  const full = fixed.length + picked.length >= max
  const found = (results.data?.results ?? []).filter((player) => !chosen.has(player.id))

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2 text-base font-semibold">{label}</legend>
      <ul className="flex flex-col gap-2" aria-label={`${label}: chosen`}>
        {fixed.map((player) => (
          <li key={player.id} className="flex min-h-12 items-center rounded-lg border bg-muted px-3">
            {player.display_name} <span className="ml-1 text-muted-foreground">(you)</span>
          </li>
        ))}
        {picked.map((player) => (
          <li key={player.id} className="flex min-h-12 items-center justify-between gap-2 rounded-lg border bg-card pl-3">
            <span className="min-w-0 break-words">{player.display_name}</span>
            <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${player.display_name}`} onClick={() => onChange(picked.filter((p) => p.id !== player.id))}>
              <X aria-hidden className="size-5" />
            </Button>
          </li>
        ))}
      </ul>
      {error && <FieldError>{error}</FieldError>}

      {!full && (
        <div className="flex flex-col gap-2">
          <div className="flex gap-2">
            <label htmlFor={id} className="sr-only">
              Find a player by name
            </label>
            <Input
              id={id}
              type="search"
              placeholder="Find a player by name"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // Inside another form: Enter searches instead of submitting the entry.
                if (e.key === "Enter") {
                  e.preventDefault()
                  setTerm(input.trim())
                }
              }}
            />
            <Button type="button" variant="outline" size="icon" aria-label="Find player" onClick={() => setTerm(input.trim())}>
              <Search aria-hidden className="size-5" />
            </Button>
          </div>
          <div aria-live="polite" className="flex flex-col gap-2">
            {term.length > 0 && term.length < MIN_SEARCH_LENGTH && <p className="text-sm text-muted-foreground">Type at least {MIN_SEARCH_LENGTH} characters.</p>}
            {results.isLoading && <p className="text-sm text-muted-foreground">Searching…</p>}
            {results.isError && <FieldError>Search isn't working right now.</FieldError>}
            {results.isSuccess && found.length === 0 && <p className="text-sm text-muted-foreground">No listed player matches “{term}”.</p>}
            {found.length > 0 && (
              <ul className="flex flex-col gap-2">
                {found.slice(0, 8).map((player) => (
                  <li key={player.id}>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto min-h-12 w-full justify-start gap-2 text-left whitespace-normal"
                      aria-label={`Add ${player.display_name}`}
                      onClick={() => {
                        onChange([...picked, { id: player.id, display_name: player.display_name }])
                        setInput("")
                        setTerm("")
                      }}
                    >
                      <Plus aria-hidden className="size-5 shrink-0" />
                      <span className="min-w-0 break-words">
                        {player.display_name}
                        {player.clubs.length > 0 && <span className="text-muted-foreground"> · {player.clubs.join(", ")}</span>}
                      </span>
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
      {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
    </fieldset>
  )
}
