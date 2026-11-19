import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Challenge = Schemas["Challenge"]
export type ChallengeInput = Schemas["ChallengeRequest"]
export type SodaSettings = Schemas["MySodaSettings"]

const BASE = "/me/soda-games/"

export const sodaKeys = {
  all: ["soda"] as const,
  list: ["soda", "list"] as const,
  settings: ["soda", "settings"] as const,
}

export const getSodaSettings = () => api<SodaSettings>("/me/soda-settings/")
export const listChallenges = () => api<Schemas["PaginatedChallengeList"]>(`${BASE}?page_size=50`)
export const createChallenge = (body: ChallengeInput) => api<Challenge>(BASE, { body })
const act = (id: string, verb: string, body: object = {}) => api<Challenge>(`${BASE}${id}/${verb}/`, { body })
export const acceptChallenge = (id: string, matchStake: boolean) => act(id, "accept", { match_stake: matchStake })
export const counterChallenge = (id: string, playAt: string) => act(id, "counter", { play_at: playAt })
export const declineChallenge = (id: string) => act(id, "decline")
export const withdrawChallenge = (id: string) => act(id, "withdraw")
export const recordResult = (id: string, games: number[][]) => act(id, "result", { games })
export const confirmResult = (id: string) => act(id, "confirm")
export const disputeResult = (id: string, reason: string) => act(id, "dispute", { reason })
export const settlePledge = (id: string) => act(id, "settle")
export const shareChallenge = (id: string, share: boolean) => act(id, "share", { share })

/** The other player, from the viewer's side. */
export const opponentOf = (c: Challenge) => (c.mine === "challenger" ? c.challenged : c.challenger)

export function stakeText(c: { stake_minor?: number | null; stake_currency?: string; stake_note?: string }) {
  if (c.stake_minor != null) return `${c.stake_currency || "KES"} ${(c.stake_minor / 100).toLocaleString()}`
  return c.stake_note || ""
}

export const STATUS_LABEL: Record<Challenge["status"], string> = {
  pending: "Waiting for an answer",
  countered: "New time proposed",
  accepted: "On",
  declined: "Declined",
  withdrawn: "Withdrawn",
  played: "Played",
}
