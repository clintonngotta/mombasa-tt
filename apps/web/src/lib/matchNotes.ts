import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Private match notes (REQ-025): the owner's alone, on an official match they played or one they recorded.
export type MatchNote = Schemas["MatchNote"]
export type MatchLink = { match_id: string } | { personal_match_id: string }

export const matchNoteKeys = {
  all: ["match-notes"] as const,
  list: ["match-notes", "list"] as const,
  of: (link: MatchLink) => ["match-notes", "of", "match_id" in link ? link.match_id : link.personal_match_id] as const,
}

const NOTES = "/me/match-notes/"

export const listMatchNotes = () => api<Schemas["PaginatedMatchNoteList"]>(`${NOTES}?page_size=100`)
export async function noteFor(link: MatchLink): Promise<MatchNote | null> {
  const query = "match_id" in link ? `match=${link.match_id}` : `personal_match=${link.personal_match_id}`
  const page = await api<Schemas["PaginatedMatchNoteList"]>(`${NOTES}?${query}`)
  return page.results[0] ?? null
}
export const createMatchNote = (link: MatchLink, body: { observations: string; goals: string }) => api<MatchNote>(NOTES, { body: { ...link, ...body } })
export const updateMatchNote = (id: string, body: { observations: string; goals: string }) => api<MatchNote>(`${NOTES}${id}/`, { method: "PATCH", body })
export const deleteMatchNote = (id: string) => api<void>(`${NOTES}${id}/`, { method: "DELETE" })
