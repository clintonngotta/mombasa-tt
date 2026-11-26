import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// A tournament's review (REQ-055): what went well, what went wrong and actions for next time. Written by
// the host's competition staff once it is over; read by them and the officials of its region and country.
export type TournamentReview = Schemas["TournamentReview"]
export type ReviewAction = Schemas["ReviewAction"]
export type ReviewInput = Schemas["TournamentReviewRequest"]
export const MAX_REVIEW_ACTIONS = 30

export const reviewKey = (tournamentId: string) => ["tournaments", "review", tournamentId] as const
export const getReview = (tournamentId: string) => api<TournamentReview>(`/tournaments/${tournamentId}/review/`)
export const saveReview = (tournamentId: string, body: ReviewInput) => api<TournamentReview>(`/tournaments/${tournamentId}/review/`, { method: "PUT", body })
