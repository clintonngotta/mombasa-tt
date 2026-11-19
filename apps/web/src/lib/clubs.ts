import { useSyncExternalStore } from "react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"
import { useMe } from "@/lib/session"

export type Organization = Schemas["Organization"]
export type OrganizationKind = Schemas["KindEnum"]
type Management = Schemas["ManagementOrganization"]
export type Membership = Schemas["Membership"] & { authority?: Management["authority"]; managedOnly?: boolean }
export type JoinRequest = Schemas["JoinRequest"]
export type Invitation = Schemas["Invitation"]
export type MyInvitation = Schemas["MyInvitation"]
export type AdminHandover = Schemas["AdminHandover"]
export type OrganizationAdmin = Schemas["OrganizationAdmin"]
export type MyJoinRequest = Schemas["MyJoinRequest"]
export type JoinDecision = "approve" | "reject"
// The timezone is left to the server default (Africa/Nairobi) when registering.
export type OrganizationInput = Required<Omit<Schemas["OrganizationRequest"], "timezone">>
export type Permission = Schemas["PermissionEnum"]
export type Role = Schemas["Role"]
export type RoleInput = Schemas["PatchedRoleRequest"]
export type Member = Schemas["Member"]
export type MemberField = Schemas["MemberField"]
export type MemberFieldKind = Schemas["MemberFieldKindEnum"]
export type MemberFieldInput = Schemas["PatchedMemberFieldRequest"]
export type MemberFieldEntry = Schemas["MemberFieldEntry"]
export type FieldValue = MemberFieldEntry["value"]
export type FieldValues = Record<string, FieldValue>
export type Committee = Schemas["Committee"]
export type CommitteePosition = Schemas["Position"]
export type CommitteeField = Schemas["CommitteeField"]
export type CommitteeFieldInput = Schemas["PatchedCommitteeFieldRequest"]
export type PositionInput = Schemas["PatchedPositionInputRequest"]
export type PastHolder = Schemas["PastHolder"]

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
  regional_body: "Regional body",
}

export const FIELD_KIND_LABEL: Record<MemberFieldKind, string> = {
  text: "Text",
  number: "Number",
  date: "Date",
  boolean: "Yes or no",
  choice: "Selection",
}

// Every club query lives under "clubs", so one invalidation (or removal on sign-out) covers them all.
export const clubKeys = {
  all: ["clubs"] as const,
  search: (term: string) => ["clubs", "search", term] as const,
  memberships: ["clubs", "memberships"] as const,
  management: ["clubs", "management"] as const,
  myInvitations: ["clubs", "my-invitations"] as const,
  myJoinRequests: ["clubs", "my-join-requests"] as const,
  myAdminNominations: ["clubs", "my-admin-nominations"] as const,
  admin: (orgId: string) => ["clubs", orgId, "admin"] as const,
  joinRequests: (orgId: string) => ["clubs", orgId, "join-requests"] as const,
  invitations: (orgId: string) => ["clubs", orgId, "invitations"] as const,
  roles: (orgId: string) => ["clubs", orgId, "roles"] as const,
  members: (orgId: string, term: string) => ["clubs", orgId, "members", term] as const,
  membersAll: (orgId: string) => ["clubs", orgId, "members"] as const,
  permissions: ["clubs", "permissions"] as const,
  memberFields: (orgId: string) => ["clubs", orgId, "member-fields"] as const,
  /** Staff view of one member's custom field values. */
  memberValues: (orgId: string, membershipId: string) => ["clubs", orgId, "member-values", membershipId] as const,
  committee: (orgId: string) => ["clubs", orgId, "committee"] as const,
  committeeHistory: (orgId: string) => ["clubs", orgId, "committee", "history"] as const,
  committeeFields: (orgId: string) => ["clubs", orgId, "committee", "fields"] as const,
  committeeCandidates: (orgId: string, term: string) => ["clubs", orgId, "committee", "candidates", term] as const,
  /** The player's own member-visible values. */
  myFieldValues: (membershipId: string) => ["clubs", "my-fields", membershipId] as const,
}

const orgPath = (id: string) => `/organizations/${id}`

export const searchOrganizations = (query: string) =>
  api<Schemas["PaginatedOrganizationList"]>(`/organizations/?search=${encodeURIComponent(query)}`)
export const requestToJoin = (organizationId: string) => api<MyJoinRequest>(`${orgPath(organizationId)}/join-requests/`, { body: {} })

// A player belongs to a handful of organizations, so the first page (50) covers the switcher.
export const listMyMemberships = () => api<Schemas["PaginatedMembershipList"]>("/me/memberships/?page_size=50")
const listManagement = () => api<Management[]>("/me/managed-organizations/")
export const listMyInvitations = () => api<Schemas["PaginatedMyInvitationList"]>("/me/invitations/")
export const listMyJoinRequests = () => api<Schemas["PaginatedMyJoinRequestList"]>("/me/join-requests/")
export const acceptInvitation = (id: string) => api<MyInvitation>(`/me/invitations/${id}/accept/`, { body: {} })
export const declineInvitation = (id: string) => api<MyInvitation>(`/me/invitations/${id}/decline/`, { body: {} })

export const createOrganization = (input: OrganizationInput) => api<Organization>("/organizations/", { body: input })
export const updateOrganizationLocation = (id: string, input: Schemas["PatchedOrganizationLocationRequest"]) =>
  api<Organization>(`/organizations/${id}/`, { method: "PATCH", body: input })

// One admin per organization, handed over by nomination (REQ-045).
export const getOrganizationAdmin = (orgId: string) => api<OrganizationAdmin>(`${orgPath(orgId)}/admin/`)
export const nominateAdmin = (orgId: string, membershipId: string) =>
  api<AdminHandover>(`${orgPath(orgId)}/admin/nominate/`, { body: { membership_id: membershipId } })
export const cancelAdminNomination = (orgId: string) => api<AdminHandover>(`${orgPath(orgId)}/admin/cancel/`, { body: {} })
export const listMyAdminNominations = () => api<Schemas["PaginatedAdminHandoverList"]>("/me/admin-nominations/")
export const answerAdminNomination = (id: string, accept: boolean) =>
  api<AdminHandover>(`/me/admin-nominations/${id}/${accept ? "accept" : "decline"}/`, { body: {} })

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

// Custom member fields (REQ-005). Staff manage definitions and every member's values; a member sees and
// fills in only their own member-visible fields.
export const listMemberFields = (orgId: string) => api<MemberField[]>(`${orgPath(orgId)}/member-fields/`)
export const createMemberField = (orgId: string, body: Schemas["MemberFieldRequest"]) =>
  api<MemberField>(`${orgPath(orgId)}/member-fields/`, { body })
export const updateMemberField = (orgId: string, id: string, body: MemberFieldInput) =>
  api<MemberField>(`${orgPath(orgId)}/member-fields/${id}/`, { method: "PATCH", body })
export const setMemberFieldRetired = (orgId: string, id: string, retired: boolean) =>
  api<MemberField>(`${orgPath(orgId)}/member-fields/${id}/${retired ? "retire" : "restore"}/`, { body: {} })
export const getMemberValues = (orgId: string, membershipId: string) =>
  api<MemberFieldEntry[]>(`${orgPath(orgId)}/members/${membershipId}/fields/`)
export const saveMemberValues = (orgId: string, membershipId: string, values: FieldValues) =>
  api<MemberFieldEntry[]>(`${orgPath(orgId)}/members/${membershipId}/fields/`, { method: "PATCH", body: { values } })
export const getMyFieldValues = (membershipId: string) => api<MemberFieldEntry[]>(`/me/memberships/${membershipId}/fields/`)
export const saveMyFieldValues = (membershipId: string, values: FieldValues) =>
  api<MemberFieldEntry[]>(`/me/memberships/${membershipId}/fields/`, { method: "PATCH", body: { values } })

// Committees (REQ-045). Every member reads the committee and its history; governance staff change it, and
// each change answers with the whole committee.
const committeePath = (orgId: string) => `${orgPath(orgId)}/committee`
export const getCommittee = (orgId: string) => api<Committee>(`${committeePath(orgId)}/`)
export const listCommitteeHistory = (orgId: string) => api<Schemas["PaginatedPastHolderList"]>(`${committeePath(orgId)}/history/?page_size=50`)
export const listCommitteeCandidates = (orgId: string, term: string) =>
  api<Schemas["PaginatedCandidateList"]>(`${committeePath(orgId)}/candidates/?search=${encodeURIComponent(term)}`)
export const createPosition = (orgId: string, body: Schemas["PositionInputRequest"]) =>
  api<Committee>(`${committeePath(orgId)}/positions/`, { body })
export const updatePosition = (orgId: string, id: string, body: PositionInput) =>
  api<Committee>(`${committeePath(orgId)}/positions/${id}/`, { method: "PATCH", body })
export const reorderPositions = (orgId: string, positions: string[]) =>
  api<Committee>(`${committeePath(orgId)}/positions/reorder/`, { body: { positions } })
export const retirePosition = (orgId: string, id: string) => api<Committee>(`${committeePath(orgId)}/positions/${id}/retire/`, { body: {} })
export const assignHolder = (orgId: string, id: string, membershipId: string, startedOn?: string) =>
  api<Committee>(`${committeePath(orgId)}/positions/${id}/holder/`, {
    method: "PUT",
    body: { membership_id: membershipId, ...(startedOn ? { started_on: startedOn } : {}) },
  })
export const endHolder = (orgId: string, id: string) => api<Committee>(`${committeePath(orgId)}/positions/${id}/holder/`, { method: "DELETE" })
export const savePositionValues = (orgId: string, id: string, values: FieldValues) =>
  api<Committee>(`${committeePath(orgId)}/positions/${id}/values/`, { method: "PATCH", body: { values } })
export const listCommitteeFields = (orgId: string) => api<CommitteeField[]>(`${committeePath(orgId)}/fields/`)
export const createCommitteeField = (orgId: string, body: Schemas["CommitteeFieldRequest"]) =>
  api<CommitteeField>(`${committeePath(orgId)}/fields/`, { body })
export const updateCommitteeField = (orgId: string, id: string, body: CommitteeFieldInput) =>
  api<CommitteeField>(`${committeePath(orgId)}/fields/${id}/`, { method: "PATCH", body })
export const setCommitteeFieldRetired = (orgId: string, id: string, retired: boolean) =>
  api<CommitteeField>(`${committeePath(orgId)}/fields/${id}/${retired ? "retire" : "restore"}/`, { body: {} })

/**
 * The signed-in player's active memberships. Disabled for signed-out visitors, and `results` is empty
 * whenever the session isn't confirmed, so a cached list never outlives a logout or expired session.
 */
export function useMemberships() {
  const me = useMe()
  const query = useQuery({ queryKey: clubKeys.memberships, queryFn: listMyMemberships, enabled: me.isSuccess })
  const management = useQuery({ queryKey: clubKeys.management, queryFn: listManagement, enabled: me.isSuccess })
  const contexts = new Map<string, Membership>()
  for (const membership of query.data?.results ?? []) contexts.set(membership.organization.id, membership)
  for (const { organization, authority, permissions } of management.data ?? []) {
    const member = contexts.get(organization.id)
    contexts.set(organization.id, member ? { ...member, authority, permissions } : {
      id: organization.id,
      organization,
      permissions,
      authority,
      managedOnly: true,
      roles: [],
      status: "active",
      joined_at: "",
    })
  }
  return { query, results: me.isSuccess ? [...contexts.values()] : [] }
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
