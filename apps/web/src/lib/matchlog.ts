import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type MatchFormat = Schemas["SinglesOrDoublesEnum"]
export type MatchResult = Schemas["MatchResultEnum"]
export type Game = Schemas["Game"]
export type PersonalMatch = Schemas["PersonalMatch"]
type MatchRequest = Schemas["PersonalMatchRequest"]
type Provenance = "source" | "client_ref"
// The form always sends every field, so treat the optional request fields as present. How a record was
// made (source, client_ref) is set only by Quick Score's save.
export type PersonalMatchInput = Required<Omit<MatchRequest, Provenance>> & Pick<MatchRequest, Provenance>
export type MatchStats = Schemas["MatchStats"]

const BASE = "/me/matches/"
const labelQuery = (label?: string) => (label ? `label=${encodeURIComponent(label)}` : "")

export const matchKeys = {
  all: ["matchlog"] as const,
  list: (label?: string) => ["matchlog", "list", label ?? ""] as const,
  stats: (label?: string) => ["matchlog", "stats", label ?? ""] as const,
  labels: ["matchlog", "labels"] as const,
  detail: (id: string) => ["matchlog", "detail", id] as const,
}

export const listMatches = (label: string | undefined, page: number) =>
  api<Schemas["PaginatedPersonalMatchList"]>(`${BASE}?${[labelQuery(label), `page=${page}`].filter(Boolean).join("&")}`)

export const getMatchStats = (label?: string) => api<MatchStats>(`${BASE}stats/?${labelQuery(label)}`)
export const getMatchLabels = () => api<Schemas["MatchLabels"]>(`${BASE}labels/`)
export const getMatch = (id: string) => api<PersonalMatch>(`${BASE}${id}/`)
export const createMatch = (input: PersonalMatchInput) => api<PersonalMatch>(BASE, { body: input })
export const updateMatch = (id: string, input: PersonalMatchInput) =>
  api<PersonalMatch>(`${BASE}${id}/`, { method: "PUT", body: input })
export const deleteMatch = (id: string) => api<void>(`${BASE}${id}/`, { method: "DELETE" })

export function formatPlayedOn(date: string) {
  // Dates are calendar days; parse at noon so no timezone shifts the day.
  return new Date(`${date}T12:00:00`).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" })
}

export const RESULT_LABEL: Record<MatchResult, string> = { win: "Won", loss: "Lost", draw: "Level" }
