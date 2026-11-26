import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

/** The platform's back office at /admin (REQ-056): for platform super admins alone. The API checks that
 * on every request and answers "not found" to anyone else. */
export type PlatformOverview = Schemas["Overview"]
export type Account = Schemas["Account"]
export type AccountChange = Schemas["PatchedAccountChangeRequest"]
export type PlatformOrganization = Schemas["PlatformOrganization"]
export type PlatformCountry = Schemas["PlatformCountry"]
export type PlatformRegion = Schemas["PlatformRegion"]
export type PlatformCity = Schemas["PlatformCity"]
export type AccountFilter = "all" | "admins" | "inactive"

export const platformKeys = {
  all: ["platform"] as const,
  overview: ["platform", "overview"] as const,
  accounts: (search: string, show: AccountFilter, page: number) => ["platform", "accounts", search, show, page] as const,
  organizations: (search: string, kind: string, page: number) => ["platform", "organizations", search, kind, page] as const,
  country: (code: string) => ["platform", "country", code] as const,
}

const query = (params: Record<string, string | number>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== "" && value !== "all") search.set(key, String(value))
  return search.size ? `?${search}` : ""
}

export const getOverview = () => api<PlatformOverview>("/platform/overview/")
export const listAccounts = (search: string, show: AccountFilter, page: number) =>
  api<Schemas["PaginatedAccountList"]>(`/platform/accounts/${query({ search, show, page })}`)
export const changeAccount = (id: string, change: AccountChange) => api<Account>(`/platform/accounts/${id}/`, { method: "PATCH", body: change })
export const listOrganizations = (search: string, kind: string, page: number) =>
  api<Schemas["PaginatedPlatformOrganizationList"]>(`/platform/organizations/${query({ search, kind, page })}`)

const country = (code: string) => `/platform/countries/${encodeURIComponent(code)}/`
export const getCountry = (code: string) => api<PlatformCountry>(country(code))
export const setCatalogueOnly = (code: string, catalogueOnly: boolean) =>
  api<PlatformCountry>(country(code), { method: "PATCH", body: { catalogue_only: catalogueOnly } })
export const addRegion = (code: string, name: string) => api<PlatformRegion>(`${country(code)}regions/`, { body: { name } })
export const renameRegion = (id: number, name: string) => api<PlatformRegion>(`/platform/regions/${id}/`, { method: "PATCH", body: { name } })
export const removeRegion = (id: number) => api<void>(`/platform/regions/${id}/`, { method: "DELETE" })
export const addCity = (regionId: number, name: string) => api<PlatformCity>(`/platform/regions/${regionId}/cities/`, { body: { name } })
export const renameCity = (id: number, name: string) => api<PlatformCity>(`/platform/cities/${id}/`, { method: "PATCH", body: { name } })
export const removeCity = (id: number) => api<void>(`/platform/cities/${id}/`, { method: "DELETE" })

export const PAGE_SIZE = 20
export const dayLabel = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" }) : "never"
