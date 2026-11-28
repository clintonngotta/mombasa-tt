import { sendOrKeep } from "@/lib/offline"
import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"
import type { Tournament, TournamentEvent } from "@/lib/tournaments"

export type Entry = Schemas["Entry"]
export type MyEntry = Schemas["MyEntry"]
export type EntryStatus = Schemas["EntryStatusEnum"]
export type EntryInput = Schemas["EntryRequestRequest"]
/** What competition staff can do to an entry. */
export type StaffEntryAction = "accept" | "waitlist" | "reject" | "staff-withdraw" | "check-in" | "undo-check-in"

export const MAX_TEAM_ROSTER = 10

export const entryKeys = {
  event: (eventId: string) => ["entries", "event", eventId] as const,
  accepted: (eventId: string) => ["entries", "event", eventId, "accepted"] as const,
  mine: ["entries", "mine"] as const,
}

const base = (id: string, eventId: string) => `/tournaments/${id}/events/${eventId}/entries/`

/** Accepted entries plus the caller's own; staff get every entry. Up to 100, the API's largest page. */
/** `search` narrows to entries whose team or a player has the text in its name. */
export const listEntries = (id: string, eventId: string, status: EntryStatus | "" = "", search = "") =>
  api<Schemas["PaginatedEntryList"]>(`${base(id, eventId)}?page_size=100${status ? `&status=${status}` : ""}${search ? `&search=${encodeURIComponent(search)}` : ""}`)
/** Every entry of one status, page after page, for the draw desk: a big field is seeded as a whole. */
export async function listAllEntries(id: string, eventId: string, status: EntryStatus) {
  const first = await listEntries(id, eventId, status)
  const results = [...first.results]
  // 20 pages is 2,000 entries, far above the largest event; the bound stops a runaway loop.
  for (let page = 2; results.length < first.count && page <= 20; page++) {
    const next = await api<Schemas["PaginatedEntryList"]>(`${base(id, eventId)}?page_size=100&status=${status}&page=${page}`)
    if (next.results.length === 0) break
    results.push(...next.results)
  }
  return { ...first, results }
}
export const createEntry = (id: string, eventId: string, body: EntryInput) => api<Entry>(base(id, eventId), { body })
export const withdrawEntry = (id: string, eventId: string, entryId: string) => api<Entry>(`${base(id, eventId)}${entryId}/withdraw/`, { body: {} })
/** Checking in at the venue, where the connection may drop: kept on the device and sent later (REQ-035). */
export const selfCheckInOrKeep = (id: string, eventId: string, entryId: string, eventName: string) =>
  sendOrKeep<Entry>({ path: `${base(id, eventId)}${entryId}/self-check-in/`, label: `Check in to ${eventName}`, refresh: [["entries"], ["tournaments"]] })
export const selfCheckIn = (id: string, eventId: string, entryId: string) => api<Entry>(`${base(id, eventId)}${entryId}/self-check-in/`, { body: {} })
export const changeEntry = (id: string, eventId: string, entryId: string, action: StaffEntryAction, reason?: string) =>
  api<Entry>(`${base(id, eventId)}${entryId}/${action}/`, { body: reason === undefined ? {} : { reason } })
/** A player of the entry leaves and someone else plays in their place; the place keeps its results (TASK-155). */
export const substituteEntry = (id: string, eventId: string, entryId: string, body: { leaving_user_id: string; joining_user_id: string; reason: string }) =>
  api<Entry>(`${base(id, eventId)}${entryId}/substitute/`, { body })
export const listMyEntries = () => api<Schemas["PaginatedMyEntryList"]>("/me/entries/")

export const ENTRY_STATUS_LABEL: Record<EntryStatus, string> = {
  pending: "Waiting for the organizers",
  accepted: "Accepted",
  waitlisted: "On the waiting list",
  rejected: "Not accepted",
  withdrawn: "Withdrawn",
  pairing: "Jumbles pair",
  replaced: "Replaced by another player",
}

export const POOL_LABEL = { men: "Men's pool", women: "Women's pool" } as const

/** Still standing: pending, accepted or on the waiting list. */
export const isLive = (entry: { status: EntryStatus }) => entry.status === "pending" || entry.status === "accepted" || entry.status === "waitlisted"

/** "Tudor Smashers" for a team, otherwise the players' names. */
export function entryTitle(entry: Pick<Entry, "team_name" | "players">) {
  return entry.team_name || entry.players.map((player) => player.display_name).join(" / ")
}

/** "3 of 16 places taken" or "3 entries accepted". */
export function placesTaken(event: Pick<TournamentEvent, "accepted_count" | "capacity">) {
  if (event.capacity) return `${event.accepted_count} of ${event.capacity} places taken`
  return event.accepted_count === 1 ? "1 entry accepted" : `${event.accepted_count} entries accepted`
}

/**
 * Why a player can't enter right now, or null when they can. Mirrors the API's rules so the form isn't
 * offered when the answer would be a refusal; the server still decides.
 */
export function entryBlock(t: Pick<Tournament, "status">, event: Pick<TournamentEvent, "status" | "registration_opens_at" | "registration_closes_at">, { staff = false, now = new Date() } = {}) {
  if (t.status === "draft") return "Entries open once the tournament is published."
  if (t.status === "completed" || t.status === "cancelled" || event.status !== "scheduled") return "Entries for this event are closed."
  if (staff) return null // the organizers enter people until the event starts
  if (event.registration_opens_at && now < new Date(event.registration_opens_at)) return "Registration hasn't opened yet."
  if (event.registration_closes_at && now >= new Date(event.registration_closes_at)) return "Registration has closed."
  return null
}
