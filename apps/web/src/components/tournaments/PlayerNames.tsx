import { Fragment } from "react"
import { Link } from "react-router-dom"
import { usePlayerPath } from "@/lib/tournamentPlayers"
import { cn } from "@/lib/utils"

type Named = { id: string; display_name: string }
/** Where an entry is playing right now, in any event of the tournament. */
export type PlayingNow = { table: string; match_id: string; event_id: string; event_name: string; live: boolean }

/** A player's name. Inside a tournament it opens their record there (TASK-148); elsewhere it is text. */
export function PlayerName({ player, className }: { player: Named; className?: string }) {
  const path = usePlayerPath()
  if (!path) return <span className={className}>{player.display_name}</span>
  return (
    <Link
      to={path(player.id)}
      // Above a card's own link (a match card leads to the match), so the name stays its own target.
      className={cn("relative z-10 underline-offset-2 hover:underline focus-visible:underline", className)}
    >
      {player.display_name}
    </Link>
  )
}

/**
 * An entry as a draw names it. A pair names each player, each leading to their record; a team keeps
 * its team name, which is nobody's in particular.
 */
export function EntryNames({ entry, exceptMatch }: { entry: { title: string; players: Named[]; playing?: PlayingNow | null }; exceptMatch?: string }) {
  const badge = <PlayingBadge playing={entry.playing} exceptMatch={exceptMatch} />
  if (entry.players.length === 0 || entry.title !== entry.players.map((p) => p.display_name).join(" / "))
    return (
      <>
        {entry.title}
        {badge}
      </>
    )
  return (
    <>
      {entry.players.map((player, index) => (
        <Fragment key={player.id}>
          {index > 0 && " / "}
          <PlayerName player={player} />
        </Fragment>
      ))}
      {badge}
    </>
  )
}

/**
 * "Playing · Table 3" once scoring has begun, "At Table 3" while being called or warming up (user
 * request, 2026-11-28). Hidden on the card of the very match it is about, which says so itself.
 */
export function PlayingBadge({ playing, exceptMatch }: { playing?: PlayingNow | null; exceptMatch?: string }) {
  if (!playing || playing.match_id === exceptMatch) return null
  const text = playing.live ? `Playing · ${playing.table}` : `At ${playing.table}`
  return (
    <span
      title={`${text} (${playing.event_name})`}
      className={cn(
        "ml-1.5 inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 align-middle text-xs font-semibold whitespace-nowrap",
        playing.live ? "bg-destructive/10 text-destructive" : "bg-surface-selected text-brand-blue"
      )}
    >
      <span aria-hidden className={cn("size-1.5 rounded-full", playing.live ? "bg-destructive" : "bg-brand-blue")} />
      {text}
      <span className="sr-only"> in {playing.event_name}</span>
    </span>
  )
}
