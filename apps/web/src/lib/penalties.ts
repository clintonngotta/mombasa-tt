import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Club penalties for absences (REQ-054): governance staff set rules, the app proposes a penalty for each
// absence it finds, staff issue or waive it, and the member sees their own and may appeal once.
export type AbsenceRule = Schemas["AbsenceRule"]
export type AbsenceRuleInput = Schemas["AbsenceRuleRequest"]
export type AbsencePenalty = Schemas["AbsencePenalty"]
export type MyAbsencePenalty = Schemas["MyAbsencePenalty"]
export type Absence = AbsenceRule["applies_to"]
export type PenaltyKind = NonNullable<AbsenceRule["kind"]>

export const ABSENCES: Absence[] = ["training", "tournament", "squad"]
export const ABSENCE_LABEL: Record<Absence, string> = {
  training: "Training accepted and missed",
  tournament: "Tournament entry not checked in",
  squad: "Squad place not taken up",
}
export const KIND_LABEL: Record<PenaltyKind, string> = { warning: "Warning", suspension: "Suspension from selection", points: "Penalty points" }

const org = (orgId: string) => `/organizations/${orgId}`
export const penaltyKeys = {
  all: ["penalties"] as const,
  rules: (orgId: string) => ["penalties", orgId, "rules"] as const,
  list: (orgId: string) => ["penalties", orgId, "list"] as const,
  mine: ["penalties", "mine"] as const,
}

export const getAbsenceRules = (orgId: string) => api<AbsenceRule[]>(`${org(orgId)}/absence-rules/`)
export const saveAbsenceRules = (orgId: string, rules: Partial<AbsenceRuleInput>[]) => api<AbsenceRule[]>(`${org(orgId)}/absence-rules/`, { method: "PUT", body: { rules } })
export const listPenalties = (orgId: string) => api<AbsencePenalty[]>(`${org(orgId)}/absence-penalties/`)
export const proposePenalties = (orgId: string) => api<{ proposed: number }>(`${org(orgId)}/absence-penalties/propose/`, { body: {} })
export const issuePenalty = (orgId: string, id: string, reason: string) => api<AbsencePenalty>(`${org(orgId)}/absence-penalties/${id}/issue/`, { body: { reason } })
export const waivePenalty = (orgId: string, id: string, reason: string) => api<AbsencePenalty>(`${org(orgId)}/absence-penalties/${id}/waive/`, { body: { reason } })
export const decideAppeal = (orgId: string, id: string, upheld: boolean, note: string) => api<AbsencePenalty>(`${org(orgId)}/absence-penalties/${id}/appeal/`, { body: { upheld, note } })
export const listMyPenalties = () => api<MyAbsencePenalty[]>("/me/absence-penalties/")
export const appealPenalty = (id: string, text: string) => api<MyAbsencePenalty>(`/me/absence-penalties/${id}/appeal/`, { body: { text } })

type Cost = { kind: PenaltyKind; suspension_events?: number | null; points?: number | null; fine_minor?: number | null; currency?: string }
/** "Suspension from selection for 2 events · fine KES 200". */
export function describePenalty(p: Cost) {
  const parts = [p.kind === "suspension" ? `Suspension from selection for ${p.suspension_events} ${p.suspension_events === 1 ? "event" : "events"}` : p.kind === "points" ? `${p.points} penalty ${p.points === 1 ? "point" : "points"}` : "Warning"]
  if (p.fine_minor) parts.push(`fine ${p.currency ?? "KES"} ${(p.fine_minor / 100).toLocaleString("en-KE")}`)
  return parts.join(" · ")
}
