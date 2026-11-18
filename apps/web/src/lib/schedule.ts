import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Schedule = Schemas["Schedule"]
export type ScheduleRow = Schemas["ScheduleRow"]
export type Problem = Schemas["Problem"]
export type Slot = Schemas["SlotRequest"]
export type Recommendation = Schemas["Recommendation"]

export const scheduleKeys = {
  detail: (tournamentId: string) => ["schedule", tournamentId] as const,
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

/** The `conflicts` list a refused save carries. */
export function conflictsOf(body: unknown): Problem[] {
  const found = typeof body === "object" && body !== null ? (body as { conflicts?: unknown }).conflicts : undefined
  return Array.isArray(found) ? (found as Problem[]) : []
}
