import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Representative squads (REQ-050): competition staff pick players for a tournament away from Coast TT, in
// a rotation the app recommends; each player accepts or declines their place.
export type Squad = Schemas["Squad"]
export type SquadInput = Schemas["SquadRequest"]
export type SquadPlace = Schemas["SquadPlace"]
export type SquadCandidate = Schemas["SquadCandidate"]
export type MySquadPlace = Schemas["MySquadPlace"]
export type HistoryRow = Schemas["HistoryRow"]

const base = (orgId: string) => `/organizations/${orgId}/squads/`
export const squadKeys = {
  all: ["squads"] as const,
  list: (orgId: string) => ["squads", orgId, "list"] as const,
  detail: (orgId: string, id: string) => ["squads", orgId, "detail", id] as const,
  rotation: (orgId: string, id: string) => ["squads", orgId, "rotation", id] as const,
  history: (orgId: string) => ["squads", orgId, "history"] as const,
  mine: ["squads", "mine"] as const,
}

export const listSquads = (orgId: string) => api<Squad[]>(base(orgId))
export const getSquad = (orgId: string, id: string) => api<Squad>(`${base(orgId)}${id}/`)
export const createSquad = (orgId: string, body: SquadInput) => api<Squad>(base(orgId), { body })
export const deleteSquad = (orgId: string, id: string) => api<void>(`${base(orgId)}${id}/`, { method: "DELETE" })
export const publishSquad = (orgId: string, id: string) => api<Squad>(`${base(orgId)}${id}/publish/`, { body: {} })
export const getRotation = (orgId: string, id: string) => api<SquadCandidate[]>(`${base(orgId)}${id}/recommendation/`)
export const pickPlayer = (orgId: string, id: string, userId: string, slot: string, reason: string) =>
  api<Squad>(`${base(orgId)}${id}/places/`, { body: { user_id: userId, slot, ...(reason ? { reason } : {}) } })
export const removePlace = (orgId: string, id: string, placeId: string) => api<Squad>(`${base(orgId)}${id}/places/${placeId}/remove/`, { body: {} })
export const getSquadHistory = (orgId: string) => api<HistoryRow[]>(`${base(orgId)}history/`)

export const listMyPlaces = () => api<MySquadPlace[]>("/me/squad-places/")
export const answerPlace = (id: string, answer: "accept" | "decline") => api<MySquadPlace>(`/me/squad-places/${id}/${answer}/`, { body: {} })

export const PLACE_STATUS: Record<SquadPlace["status"], string> = { picked: "Hasn't answered", accepted: "Going", declined: "Declined", removed: "Taken out" }
