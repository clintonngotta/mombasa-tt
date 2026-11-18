import { Link } from "react-router-dom"
import { CalendarClock, CircleCheck, CircleDot, Hourglass, Radio, type LucideIcon } from "lucide-react"
import { formatInstant } from "@/lib/dates"
import { isMine, scoreLine, sideWon, spokenScore, type DrawMatch, type DrawSide } from "@/lib/draws"
import { cn } from "@/lib/utils"

type State = { label: string; icon: LucideIcon; className: string }

/** Where a match stands, in words (REQ-002: never colour alone). */
type Stateful = Pick<DrawMatch, "status" | "a" | "b" | "scheduled_at" | "tie_score" | "dispatched_at" | "table">

function matchState(match: Stateful): State {
  if (match.status === "completed") return { label: "Finished", icon: CircleCheck, className: "text-success" }
  // Sent to a table: its table and players are held (REQ-014). Nothing here says a point was played.
  if (match.dispatched_at) return { label: match.table ? `On ${match.table}` : "On a table", icon: Radio, className: "text-brand-navy" }
  // A tie whose lineups are in has begun, whether or not a rubber is decided yet.
  if (match.tie_score) return { label: "Under way", icon: Radio, className: "text-brand-navy" }
  if (!match.a.entry || !match.b?.entry) return { label: "Waiting for players", icon: Hourglass, className: "text-muted-foreground" }
  if (match.scheduled_at) return { label: "Scheduled", icon: CalendarClock, className: "text-brand-blue" }
  return { label: "To play", icon: CircleDot, className: "text-muted-foreground" }
}

export function MatchStateChip({ match }: { match: Stateful }) {
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

/** Marks one of the viewer's own entries. */
export function YouBadge() {
  return <span className="ml-1 rounded bg-brand-gold px-1 text-xs font-bold text-brand-navy">You</span>
}

/** A winner is marked with an icon and a word, not by weight alone (REQ-002). */
export function WinnerMark({ highlighted = false }: { highlighted?: boolean }) {
  return (
    <>
      <CircleCheck aria-hidden className={cn("ml-1 inline size-4", !highlighted && "text-success")} />
      <span className="sr-only"> (winner)</span>
    </>
  )
}

type Journey = {
  entryId: string | null
  onChange: (entryId: string | null) => void
}

function SideName({ side, won, align, highlighted, onJourneyChange }: {
  side: DrawSide
  won: boolean
  align: "left" | "right"
  highlighted: boolean
  onJourneyChange?: Journey["onChange"]
}) {
  const entry = side.entry
  return (
    <span className={cn("min-w-0 break-words", align === "right" && "text-right")}>
      {entry ? (
        <span
          className={won ? "font-bold" : undefined}
          onMouseEnter={onJourneyChange && (() => onJourneyChange(entry.id))}
          onMouseLeave={onJourneyChange && (() => onJourneyChange(null))}
        >
          {entry.title}
          {side.seed && <span className={cn("ml-1 text-sm font-normal", !highlighted && "text-muted-foreground")}>[{side.seed}]</span>}
          {entry.mine && <YouBadge />}
          {won && <WinnerMark highlighted={highlighted} />}
        </span>
      ) : (
        <span className={cn("text-sm italic", !highlighted && "text-muted-foreground")}>{side.awaiting}</span>
      )}
    </span>
  )
}

/**
 * One match as a card: the two sides left and right, never one above the other (REQ-002), the score
 * between them, and a line with what else is known. A bye is shown as a bye and leads nowhere.
 */
export function MatchCard({ match, to, heading, timeZone, compact = false, journey, showLive = false }: { match: DrawMatch; to?: string; heading?: string; timeZone: string; compact?: boolean; journey?: Journey; showLive?: boolean }) {
  const score = scoreLine(match)
  const detail = whenAndWhere(match, timeZone)
  const entryId = journey?.entryId
  const highlighted = entryId != null && (match.a.entry?.id === entryId || match.b?.entry?.id === entryId)
  const live = showLive && match.is_live
  const secondaryText = !highlighted && "text-muted-foreground"
  const body = (
    <>
      {heading && <span className={cn("text-sm font-semibold", secondaryText)}>{heading}</span>}
      {live && <span className="self-start rounded-sm bg-destructive px-1.5 py-0.5 text-xs font-bold text-white">Live</span>}
      <span className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <SideName side={match.a} won={sideWon(match, match.a)} align="left" highlighted={highlighted} onJourneyChange={journey?.onChange} />
        <span className={cn("font-display text-xl font-bold tabular-nums", !score && "text-sm font-normal", !score && secondaryText)}>
          <span aria-hidden>{match.b ? (score ?? "v") : "–"}</span>
          <span className="sr-only">{match.b ? `, ${spokenScore(match)}, ` : ", "}</span>
        </span>
        {match.b ? <SideName side={match.b} won={sideWon(match, match.b)} align="right" highlighted={highlighted} onJourneyChange={journey?.onChange} /> : <span className={cn("text-right font-semibold", secondaryText)}>Bye</span>}
      </span>
      {match.b && (!compact || detail) && (
        <span className={cn("flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm", secondaryText)}>
          {!compact && <MatchStateChip match={match} />}
          {detail && <span>{detail}</span>}
        </span>
      )}
    </>
  )
  const className = cn(
    "flex min-h-12 flex-col justify-center gap-1.5 rounded-xl border bg-card px-3 py-2.5",
    isMine(match) && "border-brand-blue bg-surface-selected",
    highlighted && "border-primary bg-primary text-primary-foreground",
    live && "border-destructive ring-1 ring-destructive",
  )
  if (!to || !match.b) return <div className={className}>{body}</div>
  return (
    <Link
      to={to}
      className={cn(className, "outline-none focus-visible:outline-2 focus-visible:outline-ring", !live && "hover:border-brand-blue")}
    >
      {body}
    </Link>
  )
}
