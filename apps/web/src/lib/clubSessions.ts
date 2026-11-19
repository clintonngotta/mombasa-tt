import { api, ApiError } from "@/lib/api"
import type { Schemas } from "@/lib/schema"
import type { CalendarConflict } from "@/lib/training"

export type ClubSession = Schemas["ClubSession"]
export type ClubSessionInput = Schemas["ClubSessionRequest"]
export type SessionInvitation = Schemas["SessionInvitation"]
export type MySessionInvitation = Schemas["MySessionInvitation"]
export type When = "upcoming" | "past"

const base = (orgId: string) => `/organizations/${orgId}/club-sessions/`
const MINE = "/me/session-invitations/"

export const clubSessionKeys = {
  all: ["club-sessions"] as const,
  list: (orgId: string, when: When) => ["club-sessions", orgId, when] as const,
  detail: (orgId: string, id: string) => ["club-sessions", orgId, "detail", id] as const,
  invitations: (orgId: string, id: string) => ["club-sessions", orgId, "invitations", id] as const,
  mine: (when: When) => ["club-sessions", "mine", when] as const,
}

export const listClubSessions = (orgId: string, when: When) => api<Schemas["PaginatedClubSessionList"]>(`${base(orgId)}?when=${when}&page_size=50`)
export const getClubSession = (orgId: string, id: string) => api<ClubSession>(`${base(orgId)}${id}/`)
export const createClubSession = (orgId: string, body: ClubSessionInput) => api<ClubSession>(base(orgId), { body })
export const updateClubSession = (orgId: string, id: string, body: Partial<ClubSessionInput>) => api<ClubSession>(`${base(orgId)}${id}/`, { method: "PATCH", body })
export const cancelClubSession = (orgId: string, id: string) => api<ClubSession>(`${base(orgId)}${id}/cancel/`, { body: {} })

export const listInvitations = (orgId: string, id: string) => api<SessionInvitation[]>(`${base(orgId)}${id}/invitations/`)
export const inviteMembers = (orgId: string, id: string, userIds: string[]) => api<SessionInvitation[]>(`${base(orgId)}${id}/invitations/`, { body: { user_ids: userIds } })
export const markAttendance = (orgId: string, id: string, invitationId: string, attended: boolean | null) =>
  api<SessionInvitation>(`${base(orgId)}${id}/invitations/${invitationId}/`, { method: "PATCH", body: { attended } })

export const listMyInvitations = (when: When) => api<Schemas["PaginatedMySessionInvitationList"]>(`${MINE}?when=${when}`)
export const acceptInvitation = (id: string) => api<MySessionInvitation>(`${MINE}${id}/accept/`, { body: {} })
export const declineInvitation = (id: string) => api<MySessionInvitation>(`${MINE}${id}/decline/`, { body: {} })

/** The clashes a 409 carries: the member's commitments, or what uses a chosen table. */
export function clashesOf(error: unknown): CalendarConflict[] {
  if (!(error instanceof ApiError) || error.status !== 409) return []
  const found = (error.body as { conflicts?: unknown }).conflicts
  return Array.isArray(found) ? (found as CalendarConflict[]) : []
}

export const INVITATION_STATUS: Record<SessionInvitation["status"], string> = { invited: "Invited", accepted: "Coming", declined: "Not coming" }
