import { Link } from "react-router-dom"
import { CalendarClock, CircleCheck, CircleDot, Hourglass, type LucideIcon } from "lucide-react"
import { formatInstant } from "@/lib/dates"
import { isMine, scoreLine, type DrawMatch, type DrawSide } from "@/lib/draws"
import { cn } from "@/lib/utils"

type State = { label: string; icon: LucideIcon; className: string }

/** Where a match stands, in words (REQ-002: never colour alone). */
function matchState(match: Pick<DrawMatch, "status" | "a" | "b" | "scheduled_at">): State {
  if (match.status === "completed") return { label: "Finished", icon: CircleCheck, className: "text-success" }
  if (!match.a.entry || !match.b?.entry) return { label: "Waiting for players", icon: Hourglass, className: "text-muted-foreground" }
  if (match.scheduled_at) return { label: "Scheduled", icon: CalendarClock, className: "text-brand-blue" }
  return { label: "To play", icon: CircleDot, className: "text-muted-foreground" }
}

export function MatchStateChip({ match }: { match: Pick<DrawMatch, "status" | "a" | "b" | "scheduled_at"> }) {
  const state = matchState(match)
  const Icon = state.icon
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm font-semibold", state.className)}>
      <Icon aria-hidden className="size-4" />
      {state.label}
    </span>
  )
}

/** "Sat 5 Dec, 14:30 · Table 3", or what is still unknown. */
function whenAndWhere(match: Pick<DrawMatch, "scheduled_at" | "table">, timeZone: string) {
  const parts = [match.scheduled_at ? `Est. ${formatInstant(match.scheduled_at, timeZone)}` : "", match.table].filter(Boolean)
  return parts.join(" · ")
}

function SideName({ side, won, align }: { side: DrawSide; won: boolean; align: "left" | "right" }) {
  return (
    <span className={cn("min-w-0 break-words", align === "right" && "text-right")}>
      {side.entry ? (
        <span className={won ? "font-bold" : undefined}>
          {side.entry.title}
          {side.seed && <span className="ml-1 text-sm font-normal text-muted-foreground">[{side.seed}]</span>}
          {side.entry.mine && <span className="ml-1 rounded bg-brand-gold px-1 text-xs font-bold text-brand-navy">You</span>}
          {won && <span className="sr-only"> (winner)</span>}
        </span>
      ) : (
        <span className="text-sm text-muted-foreground italic">{side.awaiting}</span>
      )}
    </span>
  )
}

/**
 * One match as a card: the two sides left and right, never one above the other (REQ-002), the score
 * between them, and a line with what else is known. A bye is shown as a bye and leads nowhere.
 */
export function MatchCard({ match, to, heading, timeZone, compact = false }: { match: DrawMatch; to?: string; heading?: string; timeZone: string; compact?: boolean }) {
  const won = (side: DrawSide) => !!side.entry && match.status === "completed" && match.winner_id === side.entry.id
  const score = scoreLine(match)
  const detail = whenAndWhere(match, timeZone)
  const body = (
    <>
      {heading && <span className="text-sm font-semibold text-muted-foreground">{heading}</span>}
      <span className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <SideName side={match.a} won={won(match.a)} align="left" />
        <span className={cn("font-display text-xl font-bold tabular-nums", !score && "text-sm font-normal text-muted-foreground")}>{match.b ? (score ?? "v") : "–"}</span>
        {match.b ? <SideName side={match.b} won={won(match.b)} align="right" /> : <span className="text-right font-semibold text-muted-foreground">Bye</span>}
      </span>
      {match.b && (!compact || detail) && (
        <span className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm text-muted-foreground">
          {!compact && <MatchStateChip match={match} />}
          {detail && <span>{detail}</span>}
        </span>
      )}
    </>
  )
  const className = cn("flex flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5", isMine(match) && "border-brand-blue bg-surface-selected")
  if (!to || !match.b) return <div className={className}>{body}</div>
  return (
    <Link to={to} className={cn(className, "outline-none hover:border-brand-blue focus-visible:ring-3 focus-visible:ring-ring/50")}>
      {body}
    </Link>
  )
}
