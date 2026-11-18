import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type TableState = Schemas["TableState"]
export type Reservation = Schemas["Reservation"]
/** A check staff may set aside when sending a match to a table. Exclusivity is never one. */
export type Override = "check_in" | "rest"

export const reservationKeys = {
  tables: (tournamentId: string) => ["reservations", "tables", tournamentId] as const,
}

const match = (tournamentId: string, eventId: string, matchId: string) => `/tournaments/${tournamentId}/events/${eventId}/matches/${matchId}/`

/** The tournament's tables in use and which are free; competition staff only. */
export const listTables = (tournamentId: string) => api<TableState[]>(`/tournaments/${tournamentId}/tables/`)
/** Send the match to a table: the table and its players are held until the result is official. */
export const dispatchMatch = (tournamentId: string, eventId: string, matchId: string, tableId: string, overrides: Override[], reason: string) =>
  api<Schemas["MatchDetail"]>(`${match(tournamentId, eventId, matchId)}dispatch/`, { body: { table_id: tableId, overrides, reason } })
export const recallMatch = (tournamentId: string, eventId: string, matchId: string, reason: string) => api<Schemas["MatchDetail"]>(`${match(tournamentId, eventId, matchId)}recall/`, { body: { reason } })

/** Which check a refusal is about, when it is one staff may set aside. */
export const OVERRIDE_FOR: Record<string, Override> = { not_checked_in: "check_in", resting: "rest" }

export const OVERRIDE_LABEL: Record<Override, string> = {
  check_in: "Send it anyway: the players are here but weren't checked in",
  rest: "Send it anyway: the players agree to play without the full rest",
}
