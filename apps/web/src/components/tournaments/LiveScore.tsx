import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { getLive, liveKeys, pollUnless, type LiveMatch, type MatchScore } from "@/lib/live"
import { CARD_REASON_LABEL } from "@/lib/scoring"
import { cn } from "@/lib/utils"

/*
 * Live views (REQ-043, TASK-084): the score as the server replayed the umpire's events, for anybody who
 * may see the tournament. They read; nothing here scores, so nothing here imports the deck or the umpire's
 * controls (test/live.test.ts checks that).
 */

type Side = "a" | "b"
export type CardShown = { side: Side; player_name: string; card: "yellow" | "yellow_red" | "red"; penalty_points: number; adviser: boolean; reason: string }

const SIDES: Side[] = ["a", "b"]
const column = (side: Side) => (side === "a" ? 0 : 1)
const gamesText = (games: number[][]) => games.map(([a, b]) => `${a}-${b}`).join(", ")

export function LiveBadge() {
  return <span className="self-start rounded-sm bg-destructive px-1.5 py-0.5 text-xs font-bold text-white">Live</span>
}

/** "Game 3", or how the sheet ended while the umpire is still to confirm it. */
function stateLine(score: MatchScore, names: Record<Side, string>): string {
  if (score.status === "completed") {
    const winner = score.winner ? names[score.winner as Side] : ""
    if (score.outcome === "retired") return `Finished: ${winner} wins, the opponent retired. Waiting for the umpire to confirm.`
    if (score.outcome === "disqualified") return `Finished: ${winner} wins by disqualification. Waiting for the umpire to confirm.`
    return `Finished: ${winner} wins. Waiting for the umpire to confirm.`
  }
  return `Game ${score.game_number}`
}

/** What is going on at the table besides the score: a time-out, an injury, the expedite system. */
function happenings(score: MatchScore, names: Record<Side, string>): string[] {
  const shown: string[] = []
  for (const side of SIDES) if (score.timeout_running[column(side)]) shown.push(`Time-out: ${names[side]}`)
  if (score.suspended) shown.push(`Play suspended: ${names[score.suspended as Side]} injured`)
  if (score.expedite) shown.push("Expedite system")
  return shown
}

function cardText(card: CardShown): string {
  const reason = CARD_REASON_LABEL[card.reason as keyof typeof CARD_REASON_LABEL] ?? card.reason
  const who = card.adviser ? "adviser" : card.player_name
  if (card.card === "yellow") return `Yellow card, ${who} (${reason.toLowerCase()})`
  if (card.card === "red") return `Red card, ${who} sent away (${reason.toLowerCase()})`
  return `Yellow and red card, ${who}: ${card.penalty_points} penalty point${card.penalty_points === 1 ? "" : "s"} (${reason.toLowerCase()})`
}

/** The match page's live score: both sides left and right, who serves, games, points, time-outs, cards. */
export function LiveScoreboard({ score, cards, names, heading = "Live score" }: { score: MatchScore; cards: CardShown[]; names: Record<Side, string>; heading?: string }) {
  const live = score.status === "in_progress"
  const notes = happenings(score, names)
  const spoken = `${names.a} ${score.games_won[0]}, ${names.b} ${score.games_won[1]} in games; ${live ? `game ${score.game_number}: ${score.points[0]}-${score.points[1]}` : ""}`
  return (
    <section aria-labelledby="live-heading" className={cn("flex flex-col gap-3 rounded-xl border bg-card p-4", live && "border-destructive ring-1 ring-destructive")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="live-heading" className="text-xl font-bold">
          {heading}
        </h2>
        {live && <LiveBadge />}
      </div>
      <p className="text-sm text-muted-foreground">{stateLine(score, names)}</p>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3" aria-hidden>
        {SIDES.map((side) => (
          <div key={side} className={cn("flex min-w-0 flex-col gap-1", side === "b" && "col-start-3 items-end text-right")}>
            <span className="flex items-center gap-1.5 font-semibold break-words">
              {side === "b" && live && score.server === side && <ServeDot />}
              {names[side]}
              {side === "a" && live && score.server === side && <ServeDot />}
            </span>
            <span className="text-sm text-muted-foreground">
              Games <span className="font-display text-lg font-bold text-foreground tabular-nums">{score.games_won[column(side)]}</span>
            </span>
            {score.timeouts[column(side)] && <span className="text-xs text-muted-foreground">Time-out used</span>}
          </div>
        ))}
        <p className="col-start-2 row-start-1 font-display text-[56px] leading-none font-bold tabular-nums">
          {live ? `${score.points[0]}–${score.points[1]}` : `${score.games_won[0]}–${score.games_won[1]}`}
        </p>
      </div>
      <p className="sr-only" aria-live="polite">
        {spoken}
      </p>
      {live && score.server_name && <p className="text-sm">Serving: {score.server_name}</p>}
      {score.games.length > 0 && <p className="text-sm text-muted-foreground">Games: {gamesText(score.games)}</p>}
      {notes.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {notes.map((note) => (
            <li key={note} className="rounded-sm bg-secondary px-2 py-1 text-sm font-semibold">
              {note}
            </li>
          ))}
        </ul>
      )}
      {cards.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm" aria-label="Cards">
          {cards.map((card, index) => (
            <li key={index} className="flex items-center gap-2">
              <span aria-hidden className={cn("inline-block h-4 w-3 rounded-[2px]", card.card === "yellow" ? "bg-yellow-400" : "bg-red-600")} />
              {cardText(card)}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ServeDot() {
  return (
    <>
      <span aria-hidden className="inline-block size-2.5 rounded-full bg-brand-blue" />
      <span className="sr-only">(serving)</span>
    </>
  )
}

const matchPath = (tournamentId: string, match: LiveMatch) => `/tournaments/${tournamentId}/events/${match.event_id}/matches/${match.match_id}`

/** One live match in a line: names, games and points, linking to the match page. */
function StripItem({ tournamentId, match, wide = false }: { tournamentId: string; match: LiveMatch; wide?: boolean }) {
  const s = match.score
  const live = s.status === "in_progress"
  const where = [match.event_name, match.round, match.rubber ? `Rubber ${match.rubber}` : "", match.table].filter(Boolean).join(" · ")
  return (
    <Link
      to={matchPath(tournamentId, match)}
      className={cn(
        "flex min-h-12 shrink-0 flex-col gap-1 rounded-xl border bg-card px-3 py-2 outline-none hover:border-brand-blue focus-visible:outline-2 focus-visible:outline-ring",
        wide ? "w-full" : "w-64",
        live && "border-destructive",
      )}
    >
      <span className="truncate text-xs text-muted-foreground">{where}</span>
      {SIDES.map((side) => (
        <span key={side} className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 truncate font-semibold">
            {live && s.server === side && <ServeDot />}
            <span className="truncate">{match[side]}</span>
          </span>
          <span className="flex shrink-0 gap-3 font-display font-bold tabular-nums">
            {match.rubbers_won && <span className="text-muted-foreground" title="Rubbers">{match.rubbers_won[column(side)]}</span>}
            <span>{s.games_won[column(side)]}</span>
            <span className="w-6 text-right">{live ? s.points[column(side)] : ""}</span>
          </span>
        </span>
      ))}
      {!live && <span className="text-xs text-muted-foreground">Finished, waiting to be confirmed</span>}
    </Link>
  )
}

/** The tournament page's strip of matches in play; nothing at all when none is. */
export function ScoreStrip({ tournamentId, socketOpen }: { tournamentId: string; socketOpen: boolean }) {
  const live = useQuery({ queryKey: liveKeys.matches(tournamentId), queryFn: () => getLive(tournamentId), refetchInterval: pollUnless(socketOpen) })
  const matches = live.data ?? []
  if (matches.length === 0) return null
  return (
    <section aria-labelledby="strip-heading" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 id="strip-heading" className="flex items-center gap-2 text-xl font-bold">
          Live now <LiveBadge />
        </h2>
        <Link to={`/tournaments/${tournamentId}/live`} className="text-sm font-semibold text-brand-blue underline-offset-4 hover:underline">
          All live matches
        </Link>
      </div>
      <ul className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        {matches.map((match) => (
          <li key={match.match_id}>
            <StripItem tournamentId={tournamentId} match={match} />
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Every match in play, one under another, for the tournament's live page. */
export function LiveList({ tournamentId, matches }: { tournamentId: string; matches: LiveMatch[] }) {
  return (
    <ul className="flex flex-col gap-2">
      {matches.map((match) => (
        <li key={match.match_id}>
          <StripItem tournamentId={tournamentId} match={match} wide />
        </li>
      ))}
    </ul>
  )
}
