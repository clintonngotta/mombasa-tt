import { api, apiUrl } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Recap = Schemas["Recap"]

const base = (t: string, e: string, m: string) => `/tournaments/${t}/events/${e}/matches/${m}/`
export const recapKey = (matchId: string) => ["recap", matchId] as const
export const getRecap = (t: string, e: string, m: string) => api<Recap>(`${base(t, e, m)}recap/`)
export const cardUrl = (t: string, e: string, m: string) => apiUrl(`${base(t, e, m)}card.png`)
