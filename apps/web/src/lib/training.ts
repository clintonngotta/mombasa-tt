import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Training (REQ-026, REQ-027): the player's equipment, drill libraries and personal plans.
export type Equipment = Schemas["Equipment"]
export type Drill = Schemas["Drill"]
export type DrillInput = Schemas["DrillRequest"]
export type TrainingPlan = Schemas["TrainingPlan"]
export type PlanItem = Schemas["PlanItem"]
export type PlanItemInput = Schemas["PatchedPlanItemRequest"]
export type UpcomingSession = Schemas["UpcomingSession"]

/** What a 409 calendar_conflict carries: the commitments a session would overlap. */
export type CalendarConflict = { kind: "training" | "match"; title: string; starts_at: string; ends_at: string }

/** Personal training is in the player's own timezone: plans aren't tied to a club. */
export const LOCAL_TIME_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone

export const trainingKeys = {
  all: ["training"] as const,
  equipment: ["training", "equipment"] as const,
  myDrills: ["training", "drills"] as const,
  clubDrills: (orgId: string) => ["training", "club-drills", orgId] as const,
  plans: ["training", "plans"] as const,
  plan: (id: string) => ["training", "plans", id] as const,
  upcoming: ["training", "upcoming"] as const,
}

export const getEquipment = () => api<Equipment>("/me/equipment/")
export const saveEquipment = (body: Schemas["EquipmentRequest"]) => api<Equipment>("/me/equipment/", { method: "PUT", body })

export const listMyDrills = () => api<Schemas["PaginatedDrillList"]>("/me/drills/?page_size=100")
export const createMyDrill = (body: DrillInput) => api<Drill>("/me/drills/", { body })
export const updateMyDrill = (id: string, body: Schemas["PatchedDrillRequest"]) => api<Drill>(`/me/drills/${id}/`, { method: "PATCH", body })
export const deleteMyDrill = (id: string) => api<void>(`/me/drills/${id}/`, { method: "DELETE" })

export const listClubDrills = (orgId: string) => api<Drill[]>(`/organizations/${orgId}/drills/`)
export const createClubDrill = (orgId: string, body: DrillInput) => api<Drill>(`/organizations/${orgId}/drills/`, { body })
export const updateClubDrill = (orgId: string, id: string, body: Schemas["PatchedDrillRequest"]) =>
  api<Drill>(`/organizations/${orgId}/drills/${id}/`, { method: "PATCH", body })
export const deleteClubDrill = (orgId: string, id: string) => api<void>(`/organizations/${orgId}/drills/${id}/`, { method: "DELETE" })

export const listPlans = () => api<Schemas["PaginatedTrainingPlanList"]>("/me/training-plans/?page_size=50")
export const getPlan = (id: string) => api<TrainingPlan>(`/me/training-plans/${id}/`)
export const createPlan = (body: Schemas["TrainingPlanRequest"]) => api<TrainingPlan>("/me/training-plans/", { body })
export const updatePlan = (id: string, body: Schemas["PatchedTrainingPlanRequest"]) =>
  api<TrainingPlan>(`/me/training-plans/${id}/`, { method: "PATCH", body })
export const deletePlan = (id: string) => api<void>(`/me/training-plans/${id}/`, { method: "DELETE" })

/** Each item change answers with the whole plan, progress included. */
export const addPlanItem = (planId: string, body: Schemas["PlanItemRequest"]) =>
  api<TrainingPlan>(`/me/training-plans/${planId}/items/`, { body })
export const updatePlanItem = (planId: string, id: string, body: PlanItemInput) =>
  api<TrainingPlan>(`/me/training-plans/${planId}/items/${id}/`, { method: "PATCH", body })
export const deletePlanItem = (planId: string, id: string) =>
  api<TrainingPlan>(`/me/training-plans/${planId}/items/${id}/`, { method: "DELETE" })

export const listUpcomingSessions = () => api<UpcomingSession[]>("/me/training-sessions/")
