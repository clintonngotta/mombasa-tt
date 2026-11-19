import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Guests (REQ-003): players a club's staff enter before they have an account, and their claims.
export type Guest = Schemas["Guest"]
export type GuestClaim = Schemas["GuestClaim"]
export type MyGuestInvitation = Schemas["MyGuestInvitation"]
export type MyClaim = Schemas["MyClaim"]

export const guestKeys = {
  all: ["guests"] as const,
  list: (orgId: string, term = "") => ["guests", orgId, "list", term] as const,
  claims: (orgId: string) => ["guests", orgId, "claims"] as const,
  myInvitations: ["guests", "me", "invitations"] as const,
  myClaims: ["guests", "me", "claims"] as const,
}

const club = (orgId: string) => `/organizations/${orgId}/guests/`
const claimsOf = (orgId: string) => `/organizations/${orgId}/guest-claims/`

export const listGuests = (orgId: string, term = "", claimed?: boolean) => {
  const query = new URLSearchParams()
  if (term) query.set("search", term)
  if (claimed !== undefined) query.set("claimed", String(claimed))
  const tail = query.size ? `?${query}` : ""
  return api<Schemas["PaginatedGuestList"]>(`${club(orgId)}${tail}`)
}
export const createGuest = (orgId: string, displayName: string) => api<Guest>(club(orgId), { body: { display_name: displayName } })
export const renameGuest = (orgId: string, id: string, displayName: string) =>
  api<Guest>(`${club(orgId)}${id}/`, { method: "PATCH", body: { display_name: displayName } })
export const inviteGuest = (orgId: string, id: string, email: string) => api<Guest>(`${club(orgId)}${id}/invite/`, { body: { email } })
export const revokeGuestInvitation = (orgId: string, id: string) => api<Guest>(`${club(orgId)}${id}/revoke-invitation/`, { body: {} })

export const listGuestClaims = (orgId: string) => api<Schemas["PaginatedGuestClaimList"]>(claimsOf(orgId))
export const retryGuestClaim = (orgId: string, id: string, note: string) => api<GuestClaim>(`${claimsOf(orgId)}${id}/retry/`, { body: { note } })
export const rejectGuestClaim = (orgId: string, id: string, note: string) => api<GuestClaim>(`${claimsOf(orgId)}${id}/reject/`, { body: { note } })

export const listMyGuestInvitations = () => api<Schemas["PaginatedMyGuestInvitationList"]>("/me/guest-invitations/")
export const acceptGuestInvitation = (id: string) => api<MyClaim>(`/me/guest-invitations/${id}/accept/`, { body: {} })
export const declineGuestInvitation = (id: string) => api<void>(`/me/guest-invitations/${id}/decline/`, { body: {} })
export const listMyClaims = () => api<Schemas["PaginatedMyClaimList"]>("/me/guest-claims/")

export const CLAIM_ACTION: Record<Schemas["GuestClaimActionEnum"], string> = {
  accepted: "Accepted the invitation",
  merged: "Moved to the player's account",
  conflict: "Clashed, nothing moved",
  retried: "Staff tried again",
  rejected: "Staff rejected the claim",
}
