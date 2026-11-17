import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Draw = Schemas["Draw"]
export type DrawMatch = Schemas["Match"]
export type DrawSide = Schemas["MatchSide"]
export type EventDraw = Schemas["EventDraw"]

export const drawKeys = {
  event: (eventId: string) => ["draws", "event", eventId] as const,
}

const base = (id: string, eventId: string) => `/tournaments/${id}/events/${eventId}/draw/`

/** The published draw and, for competition staff, the preview. */
export const getDraw = (id: string, eventId: string) => api<EventDraw>(base(id, eventId))
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
