import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { BackLink } from "@/components/layout/BackLink"
import { FormAlert } from "@/components/forms/Field"
import { LiveBadge, LiveList } from "@/components/tournaments/LiveScore"
import { ApiError, errorMessage } from "@/lib/api"
import { getLive, liveKeys, pollUnless, useLiveTournament } from "@/lib/live"
import { getTournament, tournamentKeys } from "@/lib/tournaments"

/** Every match of a tournament being scored now (REQ-043): for spectators, players and staff alike. */
export function LivePage() {
  const { id = "" } = useParams()
  const socketOpen = useLiveTournament(id)
  const tournament = useQuery({ queryKey: tournamentKeys.detail(id), queryFn: () => getTournament(id) })
  const live = useQuery({ queryKey: liveKeys.matches(id), queryFn: () => getLive(id), refetchInterval: pollUnless(socketOpen) })
  const failed = tournament.error ?? live.error
  const missing = failed instanceof ApiError && failed.status === 404
  const matches = live.data ?? []
  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <BackLink to={`/tournaments/${id}`}>{tournament.data?.name ?? "Tournament"}</BackLink>
      <h1 className="flex items-center gap-2 text-[32px] leading-9 font-bold">
        Live matches {matches.length > 0 && <LiveBadge />}
      </h1>
      {missing && <FormAlert>This tournament doesn't exist or hasn't been published.</FormAlert>}
      {failed && !missing && <FormAlert>{errorMessage(failed, "We couldn't load the live matches.")}</FormAlert>}
      {live.isPending && !failed && <p className="text-muted-foreground">Loading live matches…</p>}
      {live.isSuccess && matches.length === 0 && <p className="text-muted-foreground">No match is being scored right now. Scores show here as soon as an umpire starts one.</p>}
      {matches.length > 0 && <LiveList tournamentId={id} matches={matches} />}
      <p className="text-sm text-muted-foreground">{socketOpen ? "Scores update as they happen." : "Reconnecting: scores update every few seconds meanwhile."}</p>
    </div>
  )
}
