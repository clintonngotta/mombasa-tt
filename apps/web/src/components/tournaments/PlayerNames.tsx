import { Fragment } from "react"
import { Link } from "react-router-dom"
import { usePlayerPath } from "@/lib/tournamentPlayers"
import { cn } from "@/lib/utils"

type Named = { id: string; display_name: string }

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
export function EntryNames({ entry }: { entry: { title: string; players: Named[] } }) {
  if (entry.players.length === 0 || entry.title !== entry.players.map((p) => p.display_name).join(" / ")) return <>{entry.title}</>
  return (
    <>
      {entry.players.map((player, index) => (
        <Fragment key={player.id}>
          {index > 0 && " / "}
          <PlayerName player={player} />
        </Fragment>
      ))}
    </>
  )
}
