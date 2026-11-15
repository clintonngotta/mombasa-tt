import { useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight, Search, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { MIN_SEARCH_LENGTH, profileKeys, searchPlayers } from "@/lib/profile"

/** Opted-in player directory (REQ-006): name, nickname and clubs only. */
export function PlayersPage() {
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")
  const results = useQuery({
    queryKey: profileKeys.search(term),
    queryFn: () => searchPlayers(term),
    enabled: term.length >= MIN_SEARCH_LENGTH,
  })
  const players = results.data?.results ?? []

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="flex max-w-[720px] flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[32px] leading-9 font-bold">Players</h1>
        <p className="text-muted-foreground">Only players who chose to be listed appear here.</p>
      </div>

      <form role="search" onSubmit={onSearch} className="flex gap-2">
        <label htmlFor="find-player" className="sr-only">
          Player name or nickname
        </label>
        <Input
          id="find-player"
          type="search"
          placeholder="Name or nickname"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <Button type="submit" size="icon" aria-label="Search">
          <Search aria-hidden className="size-5" />
        </Button>
      </form>

      <section aria-live="polite" className="flex flex-col gap-3">
        {term.length === 0 && <p className="text-muted-foreground">Search by name or nickname to find a player.</p>}
        {term.length > 0 && term.length < MIN_SEARCH_LENGTH && (
          <p className="text-muted-foreground">Type at least {MIN_SEARCH_LENGTH} characters.</p>
        )}
        {results.isLoading && <p className="text-muted-foreground">Searching…</p>}
        {results.isError && <FormAlert>{errorMessage(results.error, "Search isn't working right now.")}</FormAlert>}
        {results.isSuccess && players.length === 0 && (
          <p className="text-muted-foreground">No listed player matches “{term}”.</p>
        )}
        <ul className="flex flex-col gap-2">
          {players.map((player) => (
            <li key={player.id}>
              <Link
                to={`/players/${player.id}`}
                className="flex items-center gap-3 rounded-xl border bg-card p-4 outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-surface-selected">
                  <UserRound aria-hidden className="size-6 text-brand-blue" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate font-semibold">
                    {player.display_name}
                    {player.nickname && <span className="font-normal text-muted-foreground"> “{player.nickname}”</span>}
                  </span>
                  <span className="truncate text-sm text-muted-foreground">{player.clubs.join(" · ") || "No club listed"}</span>
                </span>
                <ChevronRight aria-hidden className="size-5 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
