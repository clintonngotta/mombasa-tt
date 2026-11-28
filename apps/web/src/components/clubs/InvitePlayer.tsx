import { useId, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search, UserPlus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { FieldError, FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { clubKeys, sendInvitation } from "@/lib/clubs"
import { MIN_SEARCH_LENGTH, playerKeys, searchPlayers } from "@/lib/profile"

/**
 * Find a player already on Coast TT and invite them to the club or team (REQ-004, REQ-057). Only players
 * listed in the player directory can be found. They join once they accept; staff never see their email.
 */
export function InvitePlayer({ orgId, noun, members }: { orgId: string; noun: string; members: Set<string> }) {
  const id = useId()
  const queryClient = useQueryClient()
  const [input, setInput] = useState("")
  const [term, setTerm] = useState("")
  const [invited, setInvited] = useState<Record<string, string>>({})
  const results = useQuery({ queryKey: playerKeys.search(term), queryFn: () => searchPlayers(term), enabled: term.length >= MIN_SEARCH_LENGTH })
  const invite = useMutation({
    mutationFn: (player: { id: string; display_name: string }) => sendInvitation(orgId, { player_id: player.id }),
    onSuccess: (_, player) => {
      setInvited((done) => ({ ...done, [player.id]: player.display_name }))
      void queryClient.invalidateQueries({ queryKey: clubKeys.invitations(orgId) })
    },
  })
  const found = results.data?.results ?? []

  function onSearch(e: FormEvent) {
    e.preventDefault()
    setTerm(input.trim())
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Players who are listed in the player directory. They get an invitation and join the {noun} once they accept.
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
          <p className="text-sm text-muted-foreground">No listed player matches “{term}”. Add them as someone new instead.</p>
        )}
        {invite.isError && <FormAlert>{errorMessage(invite.error, "We couldn't send the invitation.")}</FormAlert>}
        {found.length > 0 && (
          <ul className="flex flex-col gap-2" aria-label="Players found">
            {found.slice(0, 8).map((player) => {
              const member = members.has(player.id)
              const sent = player.id in invited
              return (
                <li key={player.id} className="flex min-h-12 items-center justify-between gap-2 rounded-lg border bg-card py-1 pr-1 pl-3">
                  <span className="min-w-0 break-words">
                    {player.display_name}
                    {player.clubs.length > 0 && <span className="text-muted-foreground"> · {player.clubs.join(", ")}</span>}
                  </span>
                  {member ? (
                    <span className="shrink-0 px-2 text-sm text-muted-foreground">Member</span>
                  ) : sent ? (
                    <span role="status" className="shrink-0 px-2 text-sm text-success">
                      Invited
                    </span>
                  ) : (
                    <Button
                      type="button"
                      size="sm"
                      className="shrink-0"
                      aria-label={`Invite ${player.display_name}`}
                      disabled={invite.isPending && invite.variables?.id === player.id}
                      onClick={() => invite.mutate({ id: player.id, display_name: player.display_name })}
                    >
                      <UserPlus aria-hidden className="size-4" /> Invite
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
