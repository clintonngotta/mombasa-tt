import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Guests (REQ-003): players a club's staff enter before they have an account, and their claims.
export type Guest = Schemas["Guest"]
export type GuestClaim = Schemas["GuestClaim"]
export type MyGuestInvitation = Schemas["MyGuestInvitation"]
export type MyClaim = Schemas["MyClaim"]
export type InvitedGuest = Schemas["InvitedGuest"]
export type InvitationDetail = Schemas["InvitationDetail"]
/** Where to reach a player: we email the link, and staff share it by phone (WhatsApp or SMS). */
export type Contact = { email?: string; phone?: string }

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
/** With an email or phone the new guest is invited at once, and `invite_link` is the link to share. */
export const createGuest = (orgId: string, displayName: string, contact: Contact = {}) =>
  api<InvitedGuest>(club(orgId), { body: { display_name: displayName, ...contact } })
export const renameGuest = (orgId: string, id: string, displayName: string) =>
  api<Guest>(`${club(orgId)}${id}/`, { method: "PATCH", body: { display_name: displayName } })
export const inviteGuest = (orgId: string, id: string, contact: Contact) => api<InvitedGuest>(`${club(orgId)}${id}/invite/`, { body: contact })
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

// Invitation links (/join/:token): the link is the proof, so these work signed out.
export const invitationKeys = { detail: (token: string) => ["invitation", token] as const }
export const getInvitation = (token: string) => api<InvitationDetail>(`/auth/invitations/${encodeURIComponent(token)}/`)
export const joinFromInvitation = (token: string, input: Schemas["InvitationJoinRequest"]) =>
  api<Schemas["InvitationJoined"]>(`/auth/invitations/${encodeURIComponent(token)}/`, { body: input })
export const claimByLink = (token: string) => api<MyClaim>(`/auth/invitations/${encodeURIComponent(token)}/claim/`, { body: {} })

/** A WhatsApp share link for an invitation, to the player's number when staff have it. */
export function whatsappLink(link: string, name: string, club: string | undefined, phone?: string | null, member = false) {
  const text = member
    ? `Hi ${name}, ${club || "the club"} has added you as a member on Coast TT. Set your password and sign in here: ${link}`
    : `Hi ${name}, ${club || "an organizer"} has entered you on Coast TT. Join here to see your entries and check your details: ${link}`
  const to = phone ? phone.replace(/^\+/, "") : ""
  return `https://wa.me/${to}?text=${encodeURIComponent(text)}`
}
