import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Award ceremonies (REQ-049): placement awards from results, the organizers' own awards, the order they
// are presented in, and the honours a player received.
export type Ceremony = Schemas["Ceremony"]
export type Award = Schemas["Award"]
export type Honour = Schemas["Honour"]

export const ceremonyKeys = {
  all: ["ceremony"] as const,
  detail: (tournamentId: string) => ["ceremony", tournamentId] as const,
  honours: ["ceremony", "honours"] as const,
}

const base = (tournamentId: string) => `/tournaments/${tournamentId}/ceremony/`

export const getCeremony = (tournamentId: string) => api<Ceremony>(base(tournamentId))
export const saveCeremony = (tournamentId: string, body: Schemas["CeremonyRequest"]) =>
  api<Ceremony>(base(tournamentId), { method: "PUT", body })
export const generateAwards = (tournamentId: string) => api<Ceremony>(`${base(tournamentId)}generate/`, { method: "POST" })
export const publishCeremony = (tournamentId: string) => api<Ceremony>(`${base(tournamentId)}publish/`, { method: "POST" })
export const reorderAwards = (tournamentId: string, awards: string[]) => api<Ceremony>(`${base(tournamentId)}reorder/`, { body: { awards } })
export const addAward = (tournamentId: string, body: Schemas["AwardRequest"]) => api<Ceremony>(`${base(tournamentId)}awards/`, { body })
export const updateAward = (tournamentId: string, id: string, body: Schemas["PatchedAwardRequest"]) =>
  api<Ceremony>(`${base(tournamentId)}awards/${id}/`, { method: "PATCH", body })
export const deleteAward = (tournamentId: string, id: string) => api<Ceremony>(`${base(tournamentId)}awards/${id}/`, { method: "DELETE" })
export const presentAward = (tournamentId: string, id: string) => api<Ceremony>(`${base(tournamentId)}awards/${id}/present/`, { method: "POST" })

export const listHonours = () => api<Honour[]>("/me/honours/")

export const PLACE_MEDAL: Record<number, string> = { 1: "Gold", 2: "Silver", 3: "Bronze" }
