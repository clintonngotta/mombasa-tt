import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Draw = Schemas["Draw"]
export type DrawMatch = Schemas["Match"]
export type DrawSide = Schemas["MatchSide"]
export type EventDraw = Schemas["EventDraw"]
export type MatchDetail = Schemas["MatchDetail"]
export type Standings = Schemas["Standings"]
export type Tie = Schemas["Tie"]
export type Rubber = Schemas["Rubber"]

export const drawKeys = {
  all: ["draws"] as const,
  event: (eventId: string) => ["draws", "event", eventId] as const,
  standings: (eventId: string) => ["draws", "standings", eventId] as const,
  match: (matchId: string) => ["draws", "match", matchId] as const,
}

const base = (id: string, eventId: string) => `/tournaments/${id}/events/${eventId}/draw/`

/** The published draw and, for competition staff, the preview. */
export const getDraw = (id: string, eventId: string) => api<EventDraw>(base(id, eventId))
/** Group tables and knockout placements of the published draw; empty until there is one. */
export const getStandings = (id: string, eventId: string) => api<Standings>(`/tournaments/${id}/events/${eventId}/standings/`)
/** One match of the published draw. */
export const getMatch = (id: string, eventId: string, matchId: string) => api<MatchDetail>(`/tournaments/${id}/events/${eventId}/matches/${matchId}/`)
/** Hand in a team's lineup for a tie: player ids for each rubber, in the tie's order. */
export const submitLineup = (id: string, eventId: string, matchId: string, entryId: string, picks: string[][]) =>
  api<MatchDetail>(`/tournaments/${id}/events/${eventId}/matches/${matchId}/lineup/`, { body: { entry_id: entryId, picks } })
/** Staff: send both teams back to choose again. */
export const resetLineups = (id: string, eventId: string, matchId: string) => api<MatchDetail>(`/tournaments/${id}/events/${eventId}/matches/${matchId}/lineup/reset/`, { body: {} })
/** Draw the accepted entries (again); seeds are entry ids, best first. */
export const previewDraw = (id: string, eventId: string, seeds: string[]) => api<EventDraw>(`${base(id, eventId)}preview/`, { body: { seeded_entry_ids: seeds } })
/** Delete the preview, before it is published, to start the draw again. */
export const discardDraw = (id: string, eventId: string) => api<EventDraw>(`${base(id, eventId)}discard/`, { body: {} })
export const publishDraw = (id: string, eventId: string) => api<EventDraw>(`${base(id, eventId)}publish/`, { body: {} })

/** Matches of one stage (and group) by round, in playing order. */
export function byRound(matches: DrawMatch[]) {
  const rounds = new Map<number, { name: string; matches: DrawMatch[] }>()
  for (const match of matches) {
    const round = rounds.get(match.round) ?? { name: match.round_name, matches: [] }
    round.matches.push(match)
    rounds.set(match.round, round)
  }
  return [...rounds.entries()].sort(([a], [b]) => a - b).map(([, round]) => round)
}

/** "Finals" for a round of several matches, "Final" for one. */
export const roundHeading = (round: { name: string; matches: DrawMatch[] }) => (round.matches.length > 1 && !round.name.startsWith("Round") ? `${round.name}s` : round.name)

/** Who won a game: 11 points or more and two clear. A game a retirement left unfinished has no winner. */
export function gameWinner([a, b]: number[]): "a" | "b" | null {
  if (Math.max(a, b) < 11 || Math.abs(a - b) < 2) return null
  return a > b ? "a" : "b"
}

/** What a match is counted in: games won, or for a team tie the rubbers won. */
export function sideScores(match: Pick<DrawMatch, "games" | "tie_score">) {
  return match.tie_score ? { a: match.tie_score[0], b: match.tie_score[1] } : gamesWon(match)
}

/** Games won by each side, from the points of each finished game. */
export function gamesWon(match: { games: number[][] }) {
  const winners = match.games.map(gameWinner)
  return { a: winners.filter((winner) => winner === "a").length, b: winners.filter((winner) => winner === "b").length }
}

/** Whether `side` won the match. */
export const sideWon = (match: Pick<DrawMatch, "status" | "winner_id">, side: DrawSide | null) => !!side?.entry && match.status === "completed" && match.winner_id === side.entry.id

/** How a score is marked when the match wasn't played to a finish: written ("ret.") and read out (", retired"). */
export const OUTCOME_MARK: Partial<Record<DrawMatch["outcome"], { short: string; spoken: string }>> = {
  retired: { short: " ret.", spoken: ", retired" },
  disqualified: { short: " DQ", spoken: ", disqualification" },
}

/** The score as it is read out: "3 games to 1", "walkover", "1 game to 0, disqualification", "not played yet". */
export function spokenScore(match: Pick<DrawMatch, "games" | "status" | "outcome" | "tie_score">) {
  const { a, b } = sideScores(match)
  const unit = match.tie_score ? "rubbers" : "games"
  if (match.status !== "completed") return match.tie_score ? `${a} ${unit} to ${b} so far` : "not played yet"
  if (match.outcome === "walkover") return "walkover"
  if (match.outcome === "disqualified" && match.games.length === 0 && !match.tie_score) return "disqualification before play"
  return `${a} ${unit} to ${b}${OUTCOME_MARK[match.outcome]?.spoken ?? ""}`
}

/** "3–1", "W/O" for a walkover, "2–1 ret." for a retirement, "1–0 DQ" for a disqualification; null while the match isn't decided. */
export function scoreLine(match: Pick<DrawMatch, "games" | "status" | "outcome" | "tie_score">) {
  const { a, b } = sideScores(match)
  // A tie under way shows its rubbers so far.
  if (match.status !== "completed") return match.tie_score ? `${a}–${b}` : null
  if (match.outcome === "walkover") return "W/O"
  if (match.outcome === "disqualified" && match.games.length === 0 && !match.tie_score) return "DQ"
  return `${a}–${b}${OUTCOME_MARK[match.outcome]?.short ?? ""}`
}

/** What a decided match's outcome means, in words, for screen readers and the match page. */
export const OUTCOME_LABEL: Record<Exclude<DrawMatch["outcome"], "">, string> = {
  played: "Played to a finish",
  walkover: "Walkover: the match was not played",
  retired: "Retirement: the match was not finished",
  disqualified: "Disqualification: the referee disqualified the loser",
}

/** Whether one of the caller's own entries plays in the match. */
export const isMine = (match: Pick<DrawMatch, "a" | "b">) => !!match.a.entry?.mine || !!match.b?.entry?.mine

/** "Group A · Round 2" or "Semi-final". */
export function matchLabel(match: Pick<DrawMatch, "stage" | "group" | "round_name">, groups: Draw["groups"]) {
  if (match.stage === "knockout") return match.round_name
  const group = groups.length > 1 ? groups.find((candidate) => candidate.number === match.group)?.name : undefined
  return group ? `${group} · ${match.round_name}` : match.round_name
}
