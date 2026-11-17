import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Draw = Schemas["Draw"]
export type DrawMatch = Schemas["Match"]
export type DrawSide = Schemas["MatchSide"]
export type EventDraw = Schemas["EventDraw"]
export type MatchDetail = Schemas["MatchDetail"]
export type Standings = Schemas["Standings"]

export const drawKeys = {
  event: (eventId: string) => ["draws", "event", eventId] as const,
  standings: (eventId: string) => ["draws", "standings", eventId] as const,
  match: (matchId: string) => ["draws", "match", matchId] as const,
}

const base = (id: string, eventId: string) => `/tournaments/${id}/events/${eventId}/draw/`

/** The published draw and, for competition staff, the preview. */
export const getDraw = (id: string, eventId: string) => api<EventDraw>(base(id, eventId))
/** Group tables and knockout placements of the published draw; empty until there is one. */
export const getStandings = (id: string, eventId: string) => api<Schemas["Standings"]>(`/tournaments/${id}/events/${eventId}/standings/`)
/** One match of the published draw. */
export const getMatch = (id: string, eventId: string, matchId: string) => api<MatchDetail>(`/tournaments/${id}/events/${eventId}/matches/${matchId}/`)
/** Draw the accepted entries (again); seeds are entry ids, best first. */
export const previewDraw = (id: string, eventId: string, seeds: string[]) => api<EventDraw>(`${base(id, eventId)}preview/`, { body: { seeded_entry_ids: seeds } })
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

/** Games won by each side, from the points of each game. */
export function gamesWon(match: Pick<DrawMatch, "games">) {
  let a = 0
  let b = 0
  for (const [left, right] of match.games) {
    if (left > right) a += 1
    else if (right > left) b += 1
  }
  return { a, b }
}

/** "3–1", "W/O" for a walkover, "2–1 ret." for a retirement; null while the match isn't decided. */
export function scoreLine(match: Pick<DrawMatch, "games" | "status" | "outcome">) {
  if (match.status !== "completed") return null
  if (match.outcome === "walkover") return "W/O"
  const { a, b } = gamesWon(match)
  return match.outcome === "retired" ? `${a}–${b} ret.` : `${a}–${b}`
}

/** What a decided match's outcome means, in words, for screen readers and the match page. */
export const OUTCOME_LABEL: Record<Exclude<DrawMatch["outcome"], "">, string> = {
  played: "Played to a finish",
  walkover: "Walkover: the match was not played",
  retired: "Retirement: the match was not finished",
}

/** Whether one of the caller's own entries plays in the match. */
export const isMine = (match: Pick<DrawMatch, "a" | "b">) => !!match.a.entry?.mine || !!match.b?.entry?.mine

/** "Group A · Round 2" or "Semi-final". */
export function matchLabel(match: Pick<DrawMatch, "stage" | "group" | "round_name">, groups: Draw["groups"]) {
  if (match.stage === "knockout") return match.round_name
  const group = groups.length > 1 ? groups.find((candidate) => candidate.number === match.group)?.name : undefined
  return group ? `${group} · ${match.round_name}` : match.round_name
}
