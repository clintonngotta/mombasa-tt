import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type OfficialResult = Schemas["OfficialResult"]
export type Resolution = Schemas["Resolution"]
export type Outcome = OfficialResult["outcome"]
export type EntryWalkovers = Schemas["EntryWalkovers"]
export type ResultBody = { winner_entry_id: string; outcome: Outcome; games: number[][]; rubber_id: string | null; reason?: string }

export const resultKeys = {
  corrections: (tournamentId: string) => ["results", "corrections", tournamentId] as const,
}

const match = (tournamentId: string, eventId: string, matchId: string) => `/tournaments/${tournamentId}/events/${eventId}/matches/${matchId}/`

/** Competition staff record a result themselves; official at once. */
export const enterResult = (tournamentId: string, eventId: string, matchId: string, body: ResultBody) => api<Schemas["MatchDetail"]>(`${match(tournamentId, eventId, matchId)}result/`, { body })
/** The referee gives walkovers in every match an entry has left in the event (a no-show), in one go. */
export const walkOverEntry = (tournamentId: string, eventId: string, entryId: string, reason: string) =>
  api<EntryWalkovers>(`/tournaments/${tournamentId}/events/${eventId}/entries/${entryId}/walkovers/`, { body: { reason } })
/** Replace a decided result, with a reason. The earlier one is kept. */
export const correctResult = (tournamentId: string, eventId: string, matchId: string, body: ResultBody & { reason: string }) =>
  api<Schemas["MatchDetail"]>(`${match(tournamentId, eventId, matchId)}result/correct/`, { body })
/** Later matches a corrected result put in question, those waiting for a decision first. */
export const getCorrections = (tournamentId: string) => api<Resolution[]>(`/tournaments/${tournamentId}/corrections/`)
export const resolveCorrection = (tournamentId: string, id: string, choice: "keep" | "replace", note: string) => api<Resolution[]>(`/tournaments/${tournamentId}/corrections/${id}/resolve/`, { body: { choice, note } })

export const SOURCE_LABEL: Record<OfficialResult["source"], string> = {
  umpire: "Confirmed by the umpire",
  staff: "Entered by the organizers",
  correction: "Corrected",
}

/**
 * "11-5 11-7 9-11" as [[11, 5], [11, 7], [9, 11]], the left side's points first. Null when a game
 * isn't two whole numbers.
 */
export function parseGames(text: string): number[][] | null {
  const games = text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map((game) => /^(\d{1,2})[-–:](\d{1,2})$/.exec(game))
  if (games.some((game) => !game)) return null
  return games.map((game) => [Number(game![1]), Number(game![2])])
}

export const gamesText = (games: number[][]) => games.map(([a, b]) => `${a}-${b}`).join(" ")
