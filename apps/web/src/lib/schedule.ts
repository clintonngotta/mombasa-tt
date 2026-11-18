import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Schedule = Schemas["Schedule"]
export type ScheduleRow = Schemas["ScheduleRow"]
export type Problem = Schemas["Problem"]
export type Slot = Schemas["SlotRequest"]
export type Recommendation = Schemas["Recommendation"]
export type Session = Schemas["Session"]
export type SessionInput = Schemas["SessionRequest"]
export type ScheduleVersion = Schemas["ScheduleVersion"]
export type ScheduleVersionSummary = Schemas["ScheduleVersionSummary"]
export type DelayReason = Schemas["DelayReasonEnum"]

export const DELAY_REASON_LABEL: Record<DelayReason, string> = {
  late_start: "Late start",
  out_of_service: "Table out of service",
  other: "Other",
}

export const scheduleKeys = {
  detail: (tournamentId: string) => ["schedule", tournamentId] as const,
  versions: (tournamentId: string) => ["schedule", tournamentId, "versions"] as const,
  version: (tournamentId: string, number: number) => ["schedule", tournamentId, "versions", number] as const,
}

const base = (tournamentId: string) => `/tournaments/${tournamentId}/schedule/`

/** Every match still to be played and not on a table, as it is planned now; competition staff only. */
export const getSchedule = (tournamentId: string) => api<Schedule>(base(tournamentId))

export type RecommendOptions = { day_starts: string; day_ends: string; table_ids: string[] }
/** A start and table for every match. Nothing is kept until `keepSchedule`. */
export const recommendSchedule = (tournamentId: string, options: RecommendOptions) =>
  api<Recommendation>(`${base(tournamentId)}recommend/`, { body: options })
/** What would be wrong with these slots, without keeping them. */
export const checkSchedule = (tournamentId: string, slots: Slot[]) =>
  api<Schemas["Checked"]>(`${base(tournamentId)}check/`, { body: { slots } })
/** Keep these slots. Refused with `schedule_conflicts` (and a `conflicts` list) when one can't work. */
export const keepSchedule = (tournamentId: string, slots: Slot[]) =>
  api<Schedule>(base(tournamentId), { method: "PUT", body: { slots } })

/** Days are built of sessions: hours, tables and (optionally) events. The recommendation fills them. */
export const addSession = (tournamentId: string, body: SessionInput) => api<Session>(`${base(tournamentId)}sessions/`, { body })
export const removeSession = (tournamentId: string, sessionId: string) =>
  api<void>(`${base(tournamentId)}sessions/${sessionId}/`, { method: "DELETE" })

/** Publish the kept plan as the next version; people whose matches moved past the threshold are told. */
export const publishSchedule = (tournamentId: string, note: string) => api<ScheduleVersion>(`${base(tournamentId)}publish/`, { body: { note } })
/** A table starts late or is out of service: its remaining published matches, and what clashes with them, move on. */
export const delayTable = (tournamentId: string, body: Schemas["TableDelayRequest"]) =>
  api<Schemas["Delayed"]>(`${base(tournamentId)}delay/`, { body })
export const listVersions = (tournamentId: string) => api<ScheduleVersionSummary[]>(`${base(tournamentId)}versions/`)
export const getVersion = (tournamentId: string, number: number) => api<ScheduleVersion>(`${base(tournamentId)}versions/${number}/`)

/** The `conflicts` list a refused save carries. */
export function conflictsOf(body: unknown): Problem[] {
  const found = typeof body === "object" && body !== null ? (body as { conflicts?: unknown }).conflicts : undefined
  return Array.isArray(found) ? (found as Problem[]) : []
}
