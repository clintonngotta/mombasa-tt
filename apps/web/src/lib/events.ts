import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type ListedEvent = Schemas["ListedEvent"]
export type ExternalEvent = Schemas["ExternalEvent"]
export type ExternalEventInput = Schemas["ExternalEventRequest"]
export type EventFilters = { when: "upcoming" | "past" | ""; from: string; to: string; town: string; category: string; ours: boolean }

export const eventKeys = {
  all: ["events"] as const,
  list: (filters: EventFilters) => ["events", "list", filters] as const,
  club: (orgId: string) => ["events", "club", orgId] as const,
  review: ["events", "review"] as const,
}

export const listEvents = (f: EventFilters) => {
  const params = new URLSearchParams()
  if (f.when) params.set("when", f.when)
  if (f.from) params.set("from", f.from)
  if (f.to) params.set("to", f.to)
  if (f.town.trim()) params.set("town", f.town.trim())
  if (f.category) params.set("category", f.category)
  if (f.ours) params.set("ours", "true")
  return api<ListedEvent[]>(`/events/?${params}`)
}

const club = (orgId: string) => `/organizations/${orgId}/external-events/`
export const listClubEvents = (orgId: string) => api<ExternalEvent[]>(club(orgId))
export const submitEvent = (orgId: string, body: ExternalEventInput) => api<ExternalEvent>(club(orgId), { body })
export const updateEvent = (orgId: string, id: string, body: Partial<ExternalEventInput>) => api<ExternalEvent>(`${club(orgId)}${id}/`, { method: "PATCH", body })
export const markLive = (orgId: string, id: string, live: boolean) => api<ExternalEvent>(`${club(orgId)}${id}/live/`, { body: { live } })

export const reviewQueue = () => api<ExternalEvent[]>("/external-events/review/")
export const approveEvent = (id: string) => api<ExternalEvent>(`/external-events/${id}/approve/`, { body: {} })
export const rejectEvent = (id: string, note: string) => api<ExternalEvent>(`/external-events/${id}/reject/`, { body: { note } })
export const removeLiveLink = (id: string) => api<ExternalEvent>(`/external-events/${id}/remove-link/`, { body: {} })
export const reportLiveLink = (id: string, reason: string) => api<void>(`/external-events/${id}/report/`, { body: { reason } })

export const CATEGORY_LABEL: Record<string, string> = {
  singles: "Singles",
  doubles: "Doubles",
  team: "Team",
  juniors: "Juniors",
  veterans: "Veterans",
  women: "Women",
  open: "Open",
  para: "Para",
}

/** "in 5 days", "tomorrow", "today", from the event's own calendar. */
export function countdown(startsOn: string, today = new Date()) {
  const start = new Date(`${startsOn}T00:00:00`)
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const days = Math.round((start.getTime() - base.getTime()) / 86_400_000)
  if (days <= 0) return ""
  return days === 1 ? "tomorrow" : `in ${days} days`
}
