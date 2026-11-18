import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Ranking = Schemas["Ranking"]
export type RankingRow = Schemas["RankingRow"]
export type PlayerRatings = Schemas["PlayerRatings"]
export type RatingSummary = Schemas["RatingSummary"]
export type RatingChange = Schemas["RatingChange"]
export type Discipline = Ranking["discipline"]
export type ResultFilter = PlayerRatings["result"]

export const DISCIPLINE_LABEL: Record<Discipline, string> = { singles: "Singles", doubles: "Doubles" }

export const ratingKeys = {
  ranking: (discipline: Discipline, organizationId: string) => ["ratings", "ranking", discipline, organizationId] as const,
  player: (userId: string, discipline: Discipline, result: ResultFilter) => ["ratings", "player", userId, discipline, result] as const,
}

/** The ranking of one discipline: the whole platform, or one of the caller's clubs. */
export const getRanking = (discipline: Discipline, organizationId: string) => api<Ranking>(`/rankings/?discipline=${discipline}${organizationId ? `&organization=${organizationId}` : ""}`)
/** One player's ratings and the rating changes of one discipline, newest first. */
export const getPlayerRatings = (userId: string, discipline: Discipline, result: ResultFilter) => api<PlayerRatings>(`/players/${userId}/ratings/?discipline=${discipline}&result=${result}`)

/** Ratings keep full precision on the server; they are rounded only here, to show them. */
export const shown = (rating: number) => Math.round(rating).toString()
/** A rating change with its sign and one decimal: "+16.0", "−11.5". */
export const signed = (delta: number) => `${delta < 0 ? "−" : "+"}${Math.abs(delta).toFixed(1)}`
export const winRate = (won: number, played: number) => (played ? `${Math.round((won / played) * 100)}%` : "–")
