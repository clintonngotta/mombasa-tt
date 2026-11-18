import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowDownRight, ArrowUpRight } from "lucide-react"
import { FormAlert } from "@/components/forms/Field"
import { errorMessage } from "@/lib/api"
import { DEFAULT_TIME_ZONE, formatInstant } from "@/lib/dates"
import { gamesText } from "@/lib/results"
import { getPlayerRatings, ratingKeys, shown, signed, type Discipline, type RatingChange, type ResultFilter } from "@/lib/ratings"
import { cn } from "@/lib/utils"

/** A player's rating changes in one discipline, newest first: each rated match with the rating before and after it (REQ-016). */
export function RatingHistory({ userId, discipline, result = "all", limit }: { userId: string; discipline: Discipline; result?: ResultFilter; limit?: number }) {
  const ratings = useQuery({ queryKey: ratingKeys.player(userId, discipline, result), queryFn: () => getPlayerRatings(userId, discipline, result) })
  if (ratings.isPending) return <p className="text-muted-foreground">Loading rating history…</p>
  if (ratings.isError) return <FormAlert>{errorMessage(ratings.error, "We couldn't load the rating history.")}</FormAlert>
  const history = limit ? ratings.data.history.slice(0, limit) : ratings.data.history
  if (history.length === 0) return <p className="text-muted-foreground">{result === "all" ? `No rated ${discipline} matches yet.` : `No rated ${discipline} matches ${result} yet.`}</p>
  return (
    <div className="flex flex-col gap-2">
      <ol className="flex flex-col gap-2">
        {history.map((change) => (
          <Change key={change.id} change={change} />
        ))}
      </ol>
      {ratings.data.count > history.length && (
        <p className="text-sm text-muted-foreground">
          Showing the latest {history.length} of {ratings.data.count}.
        </p>
      )}
    </div>
  )
}

function Change({ change }: { change: RatingChange }) {
  const Arrow = change.delta < 0 ? ArrowDownRight : ArrowUpRight
  const against = change.opponents.join(" / ") || "opponent"
  return (
    <li className="flex flex-col gap-1 rounded-lg border bg-card p-3">
      <p className="text-sm text-muted-foreground">
        {formatInstant(change.at, DEFAULT_TIME_ZONE)} ·{" "}
        <Link to={`/tournaments/${change.tournament_id}/events/${change.event_id}/matches/${change.match_id}`} className="font-semibold text-brand-blue underline-offset-4 hover:underline">
          {change.tournament_name}, {change.event_name}
          {change.rubber && `, rubber ${change.rubber}`}
        </Link>
      </p>
      <p className="font-semibold break-words">
        {change.won ? "Beat" : "Lost to"} {against}
        {change.partner && <span className="font-normal"> with {change.partner}</span>}
        {change.games.length > 0 && <span className="font-normal text-muted-foreground"> · {gamesText(change.games as number[][])}</span>}
      </p>
      <p className="flex flex-wrap items-center gap-x-2">
        <span>
          {shown(change.before)} to <span className="font-semibold">{shown(change.after)}</span>
        </span>
        <span className={cn("flex items-center gap-0.5 font-semibold", change.delta < 0 ? "text-destructive" : "text-success")}>
          <Arrow aria-hidden className="size-4" />
          {signed(change.delta)}
        </span>
        <span className="text-sm text-muted-foreground">
          {Math.round(change.expected * 100)}% expected against {shown(change.opponent)}
          {change.corrected && " · from a corrected result"}
        </span>
      </p>
    </li>
  )
}
