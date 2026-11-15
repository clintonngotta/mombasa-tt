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
export type MyJoinRequest = Schemas["MyJoinRequest"]
export type JoinDecision = "approve" | "reject"
export type OrganizationInput = Required<Schemas["OrganizationRequest"]>
export type Permission = Schemas["PermissionEnum"]
export type Role = Schemas["Role"]
export type RoleInput = Schemas["PatchedRoleRequest"]
export type Member = Schemas["Member"]

/** Whether the membership's effective permissions include any of `perms` (REQ-005). The server checks
 * every request; this only decides which actions the app offers. */
export const can = (membership: Pick<Membership, "permissions"> | undefined, ...perms: Permission[]) =>
  !!membership && perms.some((perm) => membership.permissions.includes(perm))

/** True when every permission in `perms` is one the actor holds, i.e. they may grant or remove it. */
export const withinAuthority = (membership: Pick<Membership, "permissions">, perms: readonly Permission[]) =>
  perms.every((perm) => membership.permissions.includes(perm))

/** "Admin, Captain", or "Member" when no roles are assigned. */
export const roleNames = (roles: readonly { name: string }[]) => (roles.length ? roles.map((r) => r.name).join(", ") : "Member")

export const KIND_LABEL: Record<OrganizationKind, string> = {
  club: "Club",
  facility: "Facility",
  club_facility: "Club and facility",
}

// Every club query lives under "clubs", so one invalidation (or removal on sign-out) covers them all.
export const clubKeys = {
  all: ["clubs"] as const,
  search: (term: string) => ["clubs", "search", term] as const,
  memberships: ["clubs", "memberships"] as const,
  myInvitations: ["clubs", "my-invitations"] as const,
  myJoinRequests: ["clubs", "my-join-requests"] as const,
  joinRequests: (orgId: string) => ["clubs", orgId, "join-requests"] as const,
  invitations: (orgId: string) => ["clubs", orgId, "invitations"] as const,
  roles: (orgId: string) => ["clubs", orgId, "roles"] as const,
  members: (orgId: string, term = "") => ["clubs", orgId, "members", term] as const,
  membersAll: (orgId: string) => ["clubs", orgId, "members"] as const,
  permissions: ["clubs", "permissions"] as const,
}

const orgPath = (id: string) => `/organizations/${id}`

export const searchOrganizations = (query: string) =>
  api<Schemas["PaginatedOrganizationList"]>(`/organizations/?search=${encodeURIComponent(query)}`)
export const requestToJoin = (organizationId: string) => api<MyJoinRequest>(`${orgPath(organizationId)}/join-requests/`, { body: {} })

// A player belongs to a handful of organizations, so the first page (50) covers the switcher.
export const listMyMemberships = () => api<Schemas["PaginatedMembershipList"]>("/me/memberships/?page_size=50")
export const listMyInvitations = () => api<Schemas["PaginatedMyInvitationList"]>("/me/invitations/")
export const listMyJoinRequests = () => api<Schemas["PaginatedMyJoinRequestList"]>("/me/join-requests/")
export const acceptInvitation = (id: string) => api<MyInvitation>(`/me/invitations/${id}/accept/`, { body: {} })
export const declineInvitation = (id: string) => api<MyInvitation>(`/me/invitations/${id}/decline/`, { body: {} })

export const createOrganization = (input: OrganizationInput) => api<Organization>("/organizations/", { body: input })

export const listJoinRequests = (orgId: string) => api<Schemas["PaginatedJoinRequestList"]>(`${orgPath(orgId)}/join-requests/`)
export const decideJoinRequest = (orgId: string, id: string, outcome: JoinDecision) =>
  api<JoinRequest>(`${orgPath(orgId)}/join-requests/${id}/${outcome}/`, { body: {} })

export const listInvitations = (orgId: string) => api<Schemas["PaginatedInvitationList"]>(`${orgPath(orgId)}/invitations/`)
export const sendInvitation = (orgId: string, body: Schemas["InvitationCreateRequest"]) =>
  api<Invitation>(`${orgPath(orgId)}/invitations/`, { body })
export const revokeInvitation = (orgId: string, id: string) =>
  api<Invitation>(`${orgPath(orgId)}/invitations/${id}/revoke/`, { body: {} })

export const leaveOrganization = (membershipId: string) => api<void>(`/me/memberships/${membershipId}/leave/`, { body: {} })

export const listPermissions = () => api<Schemas["PermissionInfo"][]>("/organizations/permissions/")
export const listRoles = (orgId: string) => api<Role[]>(`${orgPath(orgId)}/roles/`)
export const createRole = (orgId: string, body: Schemas["RoleRequest"]) => api<Role>(`${orgPath(orgId)}/roles/`, { body })
export const updateRole = (orgId: string, id: string, body: RoleInput) =>
  api<Role>(`${orgPath(orgId)}/roles/${id}/`, { method: "PATCH", body })
export const deleteRole = (orgId: string, id: string) => api<void>(`${orgPath(orgId)}/roles/${id}/`, { method: "DELETE" })

export const listMembers = (orgId: string, term: string) =>
  api<Schemas["PaginatedMemberList"]>(`${orgPath(orgId)}/members/?search=${encodeURIComponent(term)}`)
export const setMemberRoles = (orgId: string, membershipId: string, roles: string[]) =>
  api<Member>(`${orgPath(orgId)}/members/${membershipId}/roles/`, { method: "PUT", body: { roles } })
export const removeMember = (orgId: string, membershipId: string) =>
  api<void>(`${orgPath(orgId)}/members/${membershipId}/remove/`, { body: {} })

/**
 * The signed-in player's active memberships. Disabled for signed-out visitors, and `results` is empty
 * whenever the session isn't confirmed, so a cached list never outlives a logout or expired session.
 */
export function useMemberships() {
  const me = useMe()
  const query = useQuery({ queryKey: clubKeys.memberships, queryFn: listMyMemberships, enabled: me.isSuccess })
  return { query, results: me.isSuccess ? (query.data?.results ?? []) : [] }
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

function writeActive(id: string | null) {
  try {
    if (id === null) localStorage.removeItem(ACTIVE_KEY)
    else localStorage.setItem(ACTIVE_KEY, id)
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts only for this page load.
  }
  listeners.forEach((notify) => notify())
}

export const setActiveOrganization = (id: string) => writeActive(id)
/** Called on sign-out so the next player on a shared device doesn't inherit the choice. */
export const clearActiveOrganization = () => writeActive(null)

function subscribe(notify: () => void) {
  listeners.add(notify)
  // Other tabs change localStorage too; follow their choice.
  const onStorage = (e: StorageEvent) => {
    if (e.key === ACTIVE_KEY || e.key === null) notify()
  }
  window.addEventListener("storage", onStorage)
  return () => {
    listeners.delete(notify)
    window.removeEventListener("storage", onStorage)
  }
}

/** The active membership: the stored choice if the player still belongs there, else their first. */
export function useActiveMembership() {
  const { query, results: all } = useMemberships()
  const stored = useSyncExternalStore(subscribe, readActive, () => null)
  const active = all.find((m) => m.organization.id === stored) ?? all[0]
  return { memberships: query, all, active }
}
