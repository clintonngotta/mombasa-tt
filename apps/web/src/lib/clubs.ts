import { useSyncExternalStore } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"
import { useMe } from "@/lib/session"

export type Organization = Schemas["Organization"]
export type OrganizationKind = Schemas["KindEnum"]
export type Membership = Schemas["Membership"]
export type JoinRequest = Schemas["JoinRequest"]
export type Invitation = Schemas["Invitation"]
export type MyInvitation = Schemas["MyInvitation"]
export type OrganizationInput = Required<Schemas["OrganizationRequest"]>

export const KIND_LABEL: Record<OrganizationKind, string> = {
  club: "Club",
  facility: "Facility",
  club_facility: "Club and facility",
}

export const clubKeys = {
  memberships: ["clubs", "memberships"] as const,
  myInvitations: ["clubs", "my-invitations"] as const,
  myJoinRequests: ["clubs", "my-join-requests"] as const,
  joinRequests: (orgId: string) => ["clubs", orgId, "join-requests"] as const,
  invitations: (orgId: string) => ["clubs", orgId, "invitations"] as const,
}

const org = (id: string) => `/organizations/${id}`

// A player belongs to a handful of organizations, so the first page (50) covers the switcher.
export const listMyMemberships = () => api<Schemas["PaginatedMembershipList"]>("/me/memberships/?page_size=50")
export const listMyInvitations = () => api<Schemas["PaginatedMyInvitationList"]>("/me/invitations/")
export const listMyJoinRequests = () => api<Schemas["PaginatedMyJoinRequestList"]>("/me/join-requests/")
export const acceptInvitation = (id: string) => api<MyInvitation>(`/me/invitations/${id}/accept/`, { body: {} })
export const declineInvitation = (id: string) => api<MyInvitation>(`/me/invitations/${id}/decline/`, { body: {} })

export const createOrganization = (input: OrganizationInput) => api<Organization>("/organizations/", { body: input })

export const listJoinRequests = (orgId: string) => api<Schemas["PaginatedJoinRequestList"]>(`${org(orgId)}/join-requests/`)
export const decideJoinRequest = (orgId: string, id: string, outcome: "approve" | "reject") =>
  api<JoinRequest>(`${org(orgId)}/join-requests/${id}/${outcome}/`, { body: {} })

export const listInvitations = (orgId: string) => api<Schemas["PaginatedInvitationList"]>(`${org(orgId)}/invitations/`)
export const invite = (orgId: string, email: string) => api<Invitation>(`${org(orgId)}/invitations/`, { body: { email } })
export const revokeInvitation = (orgId: string, id: string) =>
  api<Invitation>(`${org(orgId)}/invitations/${id}/revoke/`, { body: {} })

/** The signed-in player's active memberships; disabled (and empty) for signed-out visitors. */
export function useMemberships() {
  const me = useMe()
  return useQuery({ queryKey: clubKeys.memberships, queryFn: listMyMemberships, enabled: me.isSuccess })
}

// The organization context the player last chose (REQ-004 switcher). Kept per device; the server
// still checks membership on every request, so a stale choice can only fall back, never grant access.
const ACTIVE_KEY = "mombasa-tt:active-organization"
const listeners = new Set<() => void>()

function readActive(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY)
  } catch {
    return null
  }
}

export function setActiveOrganization(id: string) {
  try {
    localStorage.setItem(ACTIVE_KEY, id)
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts only for this page load.
  }
  listeners.forEach((notify) => notify())
}

function subscribe(notify: () => void) {
  listeners.add(notify)
  return () => listeners.delete(notify)
}

/** The active membership: the stored choice if the player still belongs there, else their first. */
export function useActiveMembership() {
  const memberships = useMemberships()
  const stored = useSyncExternalStore(subscribe, readActive, () => null)
  const all = memberships.data?.results ?? []
  const active = all.find((m) => m.organization.id === stored) ?? all[0]
  return { memberships, all, active }
}
