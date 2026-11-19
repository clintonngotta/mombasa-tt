import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Price = Schemas["Pass"]
export type PriceInput = Schemas["PassRequest"]
export type DoorVisit = Schemas["Visit"]
export type MyVisit = Schemas["MyVisit"]
export type Takings = Schemas["Takings"]
export type Method = Schemas["RecordVisitRequest"]["method"]

const branch = (orgId: string, venueId: string) => `/organizations/${orgId}/venues/${venueId}/`

export const doorKeys = {
  all: ["door"] as const,
  prices: (orgId: string, venueId: string) => ["door", orgId, venueId, "prices"] as const,
  visits: (orgId: string, venueId: string, day: string) => ["door", orgId, venueId, "visits", day] as const,
  activePass: (orgId: string, venueId: string, playerId: string) => ["door", orgId, venueId, "active", playerId] as const,
  takings: (orgId: string, month: string, venue: string) => ["door", orgId, "takings", month, venue] as const,
  mine: ["door", "mine"] as const,
}

export const listPrices = (orgId: string, venueId: string) => api<Price[]>(`${branch(orgId, venueId)}passes/`)
export const createPrice = (orgId: string, venueId: string, body: PriceInput) => api<Price>(`${branch(orgId, venueId)}passes/`, { body })
export const updatePrice = (orgId: string, venueId: string, id: string, body: Partial<PriceInput>) =>
  api<Price>(`${branch(orgId, venueId)}passes/${id}/`, { method: "PATCH", body })

export const listVisits = (orgId: string, venueId: string, day: string) => api<DoorVisit[]>(`${branch(orgId, venueId)}visits/${day ? `?day=${day}` : ""}`)
export const recordVisit = (orgId: string, venueId: string, body: Schemas["RecordVisitRequest"]) => api<DoorVisit>(`${branch(orgId, venueId)}visits/`, { body })
export const reverseVisit = (orgId: string, venueId: string, id: string, reason: string) => api<DoorVisit>(`${branch(orgId, venueId)}visits/${id}/reverse/`, { body: { reason } })
export const activePassOf = (orgId: string, venueId: string, playerId: string) =>
  api<DoorVisit | null>(`${branch(orgId, venueId)}visits/active-pass/?player=${encodeURIComponent(playerId)}`)

export const getTakings = (orgId: string, month: string, venue: string) => {
  const params = new URLSearchParams()
  if (month) params.set("month", month)
  if (venue) params.set("venue", venue)
  return api<Takings>(`/organizations/${orgId}/facility-takings/?${params}`)
}

export const listMyVisits = () => api<Schemas["PaginatedMyVisitList"]>("/me/facility-visits/?page_size=50")

export const METHOD_LABEL: Record<string, string> = { cash: "Cash", mpesa: "M-Pesa", other: "Other", pass: "On their pass" }
export const KIND_LABEL: Record<Price["kind"], string> = { day: "Day pass", week: "Week pass", month: "Month pass", sessions: "Sessions bundle" }
