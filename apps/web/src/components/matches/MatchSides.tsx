import { cn } from "@/lib/utils"
import { RESULT_LABEL, type PersonalMatch } from "@/lib/matchlog"

/** Left/right identities and sets won (spec REQ-002: never stack the two sides). */
export function MatchSides({ match, size = "md" }: { match: PersonalMatch; size?: "md" | "lg" }) {
  const mine = match.format === "doubles" && match.partner_name ? `You & ${match.partner_name}` : "You"
  const theirs = match.opponent_name || "Opponent"
  const won = match.games_won > match.games_lost
  const lost = match.games_lost > match.games_won
  const score = size === "lg" ? "text-7xl" : "text-4xl"

  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
      <div className="flex min-w-0 flex-col items-start gap-1">
        <span className="font-semibold break-words">{mine}</span>
        <span className={cn("font-display leading-none font-bold tabular", score, !won && "text-muted-foreground")}>
          {match.games_won}
        </span>
      </div>
      <span aria-hidden className="font-display text-2xl text-muted-foreground">
        –
      </span>
      <div className="flex min-w-0 flex-col items-end gap-1 text-right">
        <span className="font-semibold break-words">{theirs}</span>
        <span className={cn("font-display leading-none font-bold tabular", score, !lost && "text-muted-foreground")}>
          {match.games_lost}
        </span>
      </div>
    </div>
  )
}

export function SetScores({ match }: { match: PersonalMatch }) {
  return (
    <p className="text-sm text-muted-foreground tabular">
      <span className="sr-only">Sets: </span>
      {match.games.map((g) => `${g.my_points}–${g.opponent_points}`).join(" · ")}
    </p>
  )
}

export function ResultBadge({ result }: { result: PersonalMatch["result"] }) {
  const styles = {
    win: "bg-success/10 text-success",
    loss: "bg-destructive/10 text-destructive",
    draw: "bg-muted text-muted-foreground",
  }[result]
  return <span className={cn("rounded-full px-2.5 py-0.5 text-sm font-semibold", styles)}>{RESULT_LABEL[result]}</span>
}

export function LabelPill({ label }: { label: string }) {
  return (
    <span className="rounded-full bg-surface-selected px-2.5 py-0.5 text-sm font-semibold text-brand-blue">{label}</span>
  )
}
