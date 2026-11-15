import { api } from "@/lib/api"

export type MatchFormat = "singles" | "doubles"
export type MatchResult = "win" | "loss" | "draw"
export type Game = { my_points: number; opponent_points: number }

export type PersonalMatch = {
  id: string
  played_on: string
  label: string
  format: MatchFormat
  opponent_name: string
  partner_name: string
  venue: string
  notes: string
  games: Game[]
  games_won: number
  games_lost: number
  result: MatchResult
  created_at: string
  updated_at: string
}

export type PersonalMatchInput = Pick<
  PersonalMatch,
  "played_on" | "label" | "format" | "opponent_name" | "partner_name" | "venue" | "notes" | "games"
>

export type MatchStats = {
  played: number
  won: number
  lost: number
  drawn: number
  win_rate: number | null
  games_won: number
  games_lost: number
  recent_form: MatchResult[]
  by_label: { label: string; played: number; won: number; lost: number }[]
}

type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] }

const BASE = "/me/matches/"
const labelQuery = (label?: string) => (label ? `label=${encodeURIComponent(label)}` : "")

export const matchKeys = {
  all: ["matchlog"] as const,
  list: (label?: string) => ["matchlog", "list", label ?? ""] as const,
  stats: (label?: string) => ["matchlog", "stats", label ?? ""] as const,
  labels: ["matchlog", "labels"] as const,
  detail: (id: string) => ["matchlog", "detail", id] as const,
}

export const listMatches = (label: string | undefined, page: number) =>
  api<Page<PersonalMatch>>(`${BASE}?${[labelQuery(label), `page=${page}`].filter(Boolean).join("&")}`)

export const getMatchStats = (label?: string) => api<MatchStats>(`${BASE}stats/?${labelQuery(label)}`)
export const getMatchLabels = () => api<{ labels: string[] }>(`${BASE}labels/`)
export const getMatch = (id: string) => api<PersonalMatch>(`${BASE}${id}/`)
export const createMatch = (input: PersonalMatchInput) => api<PersonalMatch>(BASE, { body: input })
export const updateMatch = (id: string, input: PersonalMatchInput) =>
  api<PersonalMatch>(`${BASE}${id}/`, { method: "PUT", body: input })
export const deleteMatch = (id: string) => api<void>(`${BASE}${id}/`, { method: "DELETE" })

export function formatPlayedOn(date: string) {
  // Dates are calendar days; parse at noon so no timezone shifts the day.
  return new Date(`${date}T12:00:00`).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" })
}

export const RESULT_LABEL: Record<MatchResult, string> = { win: "Won", loss: "Lost", draw: "Level" }
