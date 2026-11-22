import { api, apiUrl } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Announcement = Schemas["Announcement"]
export type AnnouncementScope = Schemas["AnnouncementScopeEnum"]
export type GenerateBody = Schemas["GenerateRequest"]
type Page = Schemas["PaginatedAnnouncementList"]

export const announcementKeys = {
  feed: (tournamentId: string) => ["announcements", tournamentId] as const,
}

const base = (tournamentId: string) => `/tournaments/${tournamentId}/announcements/`

export const SCOPE_LABEL: Record<AnnouncementScope, string> = {
  session: "A session",
  round: "A round",
  day: "A day",
  event: "An event",
  tournament: "The whole tournament",
}

/** The news feed, newest first: published posts for everybody, drafts too for the organizers. */
export const getAnnouncements = (tournamentId: string) => api<Page>(`${base(tournamentId)}?page_size=50`)
/** A draft drawn from the official results of the chosen scope. */
export const generateAnnouncement = (tournamentId: string, body: GenerateBody) => api<Announcement>(base(tournamentId), { body })
export const editAnnouncement = (tournamentId: string, id: string, body: { title?: string; body?: string }) =>
  api<Announcement>(`${base(tournamentId)}${id}/`, { method: "PATCH", body })
export const deleteAnnouncement = (tournamentId: string, id: string) => api<void>(`${base(tournamentId)}${id}/`, { method: "DELETE" })
/** Publish: frozen from now on. `notify` tells the tournament's players. */
export const publishAnnouncement = (tournamentId: string, id: string, notify: boolean) => api<Announcement>(`${base(tournamentId)}${id}/publish/`, { body: { notify } })
/** A new draft of a published post, drawn from the results as they stand now; the original stays. */
export const amendAnnouncement = (tournamentId: string, id: string) => api<Announcement>(`${base(tournamentId)}${id}/amend/`, { body: {} })
export const announcementCardUrl = (tournamentId: string, id: string) => apiUrl(`${base(tournamentId)}${id}/card/`)
/** Where a post is on the tournament page, for sharing. */
export const announcementLink = (tournamentId: string, id: string) => `${window.location.origin}/tournaments/${tournamentId}#news-${id}`
