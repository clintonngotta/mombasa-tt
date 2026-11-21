import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type TableState = Schemas["TableState"]
export type Reservation = Schemas["Reservation"]
/** A check staff may set aside when sending a match to a table. Exclusivity is never one. */
export type Override = "check_in" | "rest"

export type Board = Schemas["Board"]
export type BoardTable = Schemas["BoardTable"]
export type QueuedMatch = Schemas["QueuedMatch"]

export const reservationKeys = {
  tables: (tournamentId: string) => ["reservations", "tables", tournamentId] as const,
  board: (tournamentId: string) => ["reservations", "board", tournamentId] as const,
}

/** The dispatch board: tables, the ready queue in its fixed order and what is suggested; staff only. */
export const getBoard = (tournamentId: string) => api<Board>(`/tournaments/${tournamentId}/dispatch/`)
/** Switch automatic dispatch on or off; on, it sends what is ready at once. */
export const setAutoDispatch = (tournamentId: string, enabled: boolean) => api<Board>(`/tournaments/${tournamentId}/dispatch/auto/`, { body: { enabled } })
/** Let automatic dispatch look now (a rest may have just ended). Sends nothing while it is off. */
export const runAutoDispatch = (tournamentId: string) => api<Board>(`/tournaments/${tournamentId}/dispatch/run/`, { body: {} })

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

// The match-day control centre (REQ-043).
export type TableBlockReason = Schemas["TableBlockReasonEnum"]
export type DeskEntry = Schemas["DeskEntry"]
export type MatchDayLogEntry = Schemas["MatchDayLog"]

export const controlKeys = {
  desk: (tournamentId: string) => ["control", "desk", tournamentId] as const,
  log: (tournamentId: string) => ["control", "log", tournamentId] as const,
}

export const TABLE_BLOCK_REASONS: { value: TableBlockReason; label: string }[] = [
  { value: "out_of_service", label: "Out of service" },
  { value: "cleaning", label: "Being cleaned or set up" },
  { value: "reserved", label: "Kept free on purpose" },
  { value: "other", label: "Other" },
]

/** Call the match on a table again; only the sides not yet at the table are told. */
export const callAgain = (tournamentId: string, eventId: string, matchId: string) => api<Board>(`${match(tournamentId, eventId, matchId)}call/`, { body: {} })
/** A called side is at the table, or with `undo` isn't. */
export const reportSide = (tournamentId: string, eventId: string, matchId: string, side: "a" | "b", undo = false) => api<Board>(`${match(tournamentId, eventId, matchId)}report/`, { body: { side, undo } })
/** Move a match on a table to another free table, with a reason. */
export const moveMatch = (tournamentId: string, eventId: string, matchId: string, tableId: string, reason: string) => api<Board>(`${match(tournamentId, eventId, matchId)}move/`, { body: { table_id: tableId, reason } })
export const blockTable = (tournamentId: string, tableId: string, reason: TableBlockReason, note: string) => api<Board>(`/tournaments/${tournamentId}/tables/${tableId}/block/`, { body: { reason, note } })
export const unblockTable = (tournamentId: string, tableId: string) => api<Board>(`/tournaments/${tournamentId}/tables/${tableId}/unblock/`, { body: {} })
/** Accepted entries of events still to play, those not checked in first. */
export const getDesk = (tournamentId: string) => api<DeskEntry[]>(`/tournaments/${tournamentId}/check-in-desk/`)
/** The latest 200 match-day log entries, newest first. */
export const getMatchDayLog = (tournamentId: string) => api<MatchDayLogEntry[]>(`/tournaments/${tournamentId}/match-day-log/`)
