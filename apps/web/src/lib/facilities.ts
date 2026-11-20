import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Facility = Schemas["Facility"]
export type FacilityProfile = Schemas["FacilityProfile"]
export type FacilitySearch = { name: string; country: string; region: string; city: string; openNow: boolean }

export const facilityKeys = {
  all: ["facilities"] as const,
  find: (search: FacilitySearch) => ["facilities", "find", search] as const,
  detail: (id: string) => ["facilities", "detail", id] as const,
}

/** Facility branches the player may see (REQ-044), by place, name and open now. */
export const findFacilities = ({ name, country, region, city, openNow }: FacilitySearch) => {
  const params = new URLSearchParams({ page_size: "50" })
  for (const [key, value] of Object.entries({ search: name, country, region, city })) if (value.trim()) params.set(key, value.trim())
  if (openNow) params.set("open_now", "true")
  return api<Schemas["PaginatedFacilityList"]>(`/facilities/?${params}`)
}
export const getFacility = (id: string) => api<FacilityProfile>(`/facilities/${id}/`)

/** "08:00" from the API's "08:00:00". */
export const hhmm = (time: string) => time.slice(0, 5)
