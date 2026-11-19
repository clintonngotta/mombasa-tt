import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Venue = Schemas["Venue"]
export type VenueTable = Schemas["Table"]
export type VenueInput = Schemas["PatchedVenueRequest"]

// Under "clubs" so that sign-out and club-wide refreshes cover venues too.
export const venueKeys = {
  list: (orgId: string) => ["clubs", orgId, "venues"] as const,
}

const base = (orgId: string) => `/organizations/${orgId}/venues/`

/** Venues of an organization (REQ-007). Facility staff also get the ones no longer in use. */
export const listVenues = (orgId: string) => api<Venue[]>(base(orgId))
export const createVenue = (orgId: string, body: Schemas["VenueRequest"]) => api<Venue>(base(orgId), { body })
export const updateVenue = (orgId: string, id: string, body: VenueInput) => api<Venue>(`${base(orgId)}${id}/`, { method: "PATCH", body })
export const addTable = (orgId: string, venueId: string, label: string) => api<Venue>(`${base(orgId)}${venueId}/tables/`, { body: { label } })
export const updateTable = (orgId: string, venueId: string, tableId: string, body: Schemas["PatchedTableRequest"]) =>
  api<Venue>(`${base(orgId)}${venueId}/tables/${tableId}/`, { method: "PATCH", body })

export const tableCount = (venue: Venue) => {
  const count = venue.tables.filter((table) => table.active).length
  return count === 1 ? "1 table" : `${count} tables`
}

export type OpeningHour = Schemas["OpeningHour"]
export type Closure = Schemas["Closure"]
export type VenueProfile = Venue["profile"]

/** Replace the weekly opening hours and the closures together (REQ-044). */
export const saveVenueHours = (orgId: string, venueId: string, hours: OpeningHour[], closures: Closure[]) =>
  api<Venue>(`${base(orgId)}${venueId}/hours/`, { method: "PUT", body: { hours, closures } })

/** Facility organizations describe their venues as branches players can find. */
export const runsFacility = (kind: string | undefined) => kind === "facility" || kind === "club_facility"

export const PROFILE_OPTIONS: { value: VenueProfile; label: string; description: string }[] = [
  { value: "hidden", label: "Hidden", description: "Not in the facility finder" },
  { value: "members", label: "Members only", description: "Your members find it" },
  { value: "public", label: "Public", description: "Every signed-in player finds it" },
]
