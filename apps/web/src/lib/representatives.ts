import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

/** Representatives (REQ-045): a club sends members to its region's body, a regional body to the national one. */
export type Representative = Schemas["Representative"]
export type Representatives = Schemas["Representatives"]

export const representativeKeys = {
  list: (orgId: string) => ["clubs", orgId, "representatives"] as const,
}

const path = (orgId: string) => `/organizations/${orgId}/representatives/`

export const getRepresentatives = (orgId: string) => api<Representatives>(path(orgId))
export const nominateRepresentative = (orgId: string, body: Schemas["NominateRepresentativeRequest"]) => api<Representative>(path(orgId), { body })
export const withdrawRepresentative = (orgId: string, id: string) => api<Representative>(`${path(orgId)}${id}/withdraw/`, { body: {} })
export const decideRepresentative = (orgId: string, id: string, action: "accept" | "decline" | "remove", note = "") =>
  api<Representative>(`${path(orgId)}${id}/${action}/`, { body: action === "accept" ? {} : { note } })
export const setRepresentativeCap = (orgId: string, cap: number | null) => api<{ cap: number | null }>(`${path(orgId)}cap/`, { method: "PUT", body: { cap } })

const dateLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" })

export function termLabel({ term_start: start, term_end: end }: Pick<Representative, "term_start" | "term_end">) {
  if (start && end) return `Term ${dateLabel(start)} to ${dateLabel(end)}`
  if (start) return `Term from ${dateLabel(start)}`
  if (end) return `Term until ${dateLabel(end)}`
  return null
}

const ENDED: Record<string, string> = {
  replaced: "Replaced",
  recalled: "Recalled by the sender",
  removed: "Removed by the body",
  left: "Left the organization",
  term_ended: "Term ended",
}

/** One short phrase for where a nomination stands. */
export function statusLabel(representative: Representative) {
  switch (representative.status) {
    case "pending":
      return "Waiting for a decision"
    case "accepted":
      return representative.in_term ? "Representative" : "Term ended"
    case "declined":
      return "Declined"
    case "withdrawn":
      return "Withdrawn"
    default:
      return ENDED[representative.end_reason] ?? "Ended"
  }
}

export const isOpen = (representative: Representative) => representative.status === "pending" || representative.status === "accepted"
