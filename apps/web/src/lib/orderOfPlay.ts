import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type OrderOfPlay = Schemas["OrderOfPlay"]
export type OrderSlot = Schemas["OrderSlot"]
export type Stage = Schemas["Stage"]
export type NotBefore = Schemas["NotBefore"]
export type MoveReason = Schemas["MoveMatchReasonEnum"]

export const MOVE_REASON_LABEL: Record<MoveReason, string> = {
  player_request: "A player asked",
  other: "Other",
}

export const orderKeys = {
  detail: (tournamentId: string) => ["order-of-play", tournamentId] as const,
}

const base = (tournamentId: string) => `/tournaments/${tournamentId}/order-of-play/`

/** Every planned match by time and table and the order of the stages (REQ-053). Staff see it once
 * published; everybody else once it is out. */
export const getOrderOfPlay = (tournamentId: string) => api<OrderOfPlay>(base(tournamentId))
/** Save the order of the stages; every stage once. */
export const saveStages = (tournamentId: string, stages: Pick<Stage, "event_id" | "stage">[]) =>
  api<OrderOfPlay>(`${base(tournamentId)}stages/`, { method: "PUT", body: { stages } })
/** When the order of play goes public; null means now. */
export const setRelease = (tournamentId: string, releaseAt: string | null) =>
  api<OrderOfPlay>(`${base(tournamentId)}release/`, { method: "PUT", body: { release_at: releaseAt } })
/** A player can't play before `at`; with `move`, their earlier published matches move to then. */
export const setNotBefore = (tournamentId: string, userId: string, at: string, note: string, move: boolean) =>
  api<OrderOfPlay>(`${base(tournamentId)}players/${userId}/`, { method: "PUT", body: { at, note, move } })
export const clearNotBefore = (tournamentId: string, userId: string) => api<OrderOfPlay>(`${base(tournamentId)}players/${userId}/`, { method: "DELETE" })
/** Move a published match to a later start; what then clashes moves on too. */
export const moveMatchLater = (tournamentId: string, matchId: string, scheduledAt: string, reason: MoveReason, note: string) =>
  api<OrderOfPlay>(`${base(tournamentId)}matches/${matchId}/move/`, { body: { scheduled_at: scheduledAt, reason, note } })
