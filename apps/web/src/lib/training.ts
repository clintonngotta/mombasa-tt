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
export type PatternStep = Schemas["PatternStep"]
export type Activity = Schemas["Activity"]
export type Skill = Schemas["SkillEnum"]
export type Category = Schemas["DrillCategoryEnum"]
export type Level = NonNullable<Drill["level"]>
export type Phase = Schemas["PhaseEnum"]
export type Period = Schemas["PeriodEnum"]
export type Library = Schemas["LibraryEnum"]
export type Recommendation = Schemas["DrillRecommendation"]

export const SKILL_LABEL: Record<Skill, string> = {
  footwork: "Footwork",
  placement: "Placement",
  forehand: "Forehand",
  backhand: "Backhand",
  third_ball: "Third-ball attack",
  serve: "Serve",
  receive: "Receive",
  short_game: "Short game",
  topspin: "Topspin",
  blocking: "Blocking",
  consistency: "Consistency",
  transition: "FH-BH transition",
  reading_spin: "Reading spin",
  fitness: "Fitness",
  flexibility: "Flexibility",
}
export const SKILLS = Object.keys(SKILL_LABEL) as Skill[]

export const CATEGORY_LABEL: Record<Category, string> = {
  serve: "Serve",
  receive: "Receive",
  footwork: "Footwork",
  topspin: "Topspin",
  block: "Block",
  short_game: "Short game",
  multiball: "Multiball",
  match_play: "Match play",
  warm_up: "Warm-up",
  off_table: "Off the table",
  cool_down: "Cool-down",
}

export const LEVEL_LABEL: Record<string, string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced" }

export const PHASE_LABEL: Record<Phase, string> = {
  warm_up: "Warm-up",
  on_table: "On the table",
  off_table: "Off the table",
  match_play: "Match play",
  cool_down: "Cool-down",
}
export const PHASES = Object.keys(PHASE_LABEL) as Phase[]

export const LIBRARY_LABEL: Record<Library, string> = { standard: "Standard", personal: "Mine", club: "Club", coach: "Coach's" }

export const PERIOD_LABEL: Record<Period, string> = { day: "Day", week: "Week", month: "Month", custom: "Custom dates" }

/** What a 409 calendar_conflict carries: the commitments a session would overlap. */
export type CalendarConflict = {
  kind: "training" | "match" | "booking" | "club_session" | "tournament"
  title: string
  starts_at: string
  ends_at: string
  /** For a table in use: which of the chosen tables. */
  tables?: string[]
}

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
  library: ["training", "library"] as const,
  drill: (id: string) => ["training", "library", id] as const,
  recommendations: (planId: string) => ["training", "recommendations", planId] as const,
  clubPlans: (orgId: string) => ["training", "club-plans", orgId] as const,
  clubPlan: (orgId: string, id: string) => ["training", "club-plans", orgId, id] as const,
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

// The library: standard drills, the player's own and those of their clubs.
export const listLibrary = () => api<Drill[]>("/drills/")
export const getDrill = (id: string) => api<Drill>(`/drills/${id}/`)
export const listRecommendations = (planId: string) => api<Recommendation[]>(`/me/training-plans/${planId}/recommendations/`)

// A club's plans for a day, week, month or any dates (REQ-027): members read, training staff write.
const clubPlans = (orgId: string) => `/organizations/${orgId}/training-plans`
export const listClubPlans = (orgId: string) => api<Schemas["PaginatedTrainingPlanList"]>(`${clubPlans(orgId)}/?page_size=50`)
export const getClubPlan = (orgId: string, id: string) => api<TrainingPlan>(`${clubPlans(orgId)}/${id}/`)
export const createClubPlan = (orgId: string, body: Schemas["TrainingPlanRequest"]) => api<TrainingPlan>(`${clubPlans(orgId)}/`, { body })
export const updateClubPlan = (orgId: string, id: string, body: Schemas["PatchedTrainingPlanRequest"]) =>
  api<TrainingPlan>(`${clubPlans(orgId)}/${id}/`, { method: "PATCH", body })
export const deleteClubPlan = (orgId: string, id: string) => api<void>(`${clubPlans(orgId)}/${id}/`, { method: "DELETE" })
export const listClubRecommendations = (orgId: string, id: string) => api<Recommendation[]>(`${clubPlans(orgId)}/${id}/recommendations/`)
export const addClubPlanItem = (orgId: string, planId: string, body: Schemas["PlanItemRequest"]) =>
  api<TrainingPlan>(`${clubPlans(orgId)}/${planId}/items/`, { body })
export const updateClubPlanItem = (orgId: string, planId: string, id: string, body: PlanItemInput) =>
  api<TrainingPlan>(`${clubPlans(orgId)}/${planId}/items/${id}/`, { method: "PATCH", body })
export const deleteClubPlanItem = (orgId: string, planId: string, id: string) =>
  api<TrainingPlan>(`${clubPlans(orgId)}/${planId}/items/${id}/`, { method: "DELETE" })

/** Everything a plan screen does, for a player's own plan or a club's. */
export type PlanApi = {
  key: readonly unknown[]
  listKey: readonly unknown[]
  get: () => Promise<TrainingPlan>
  update: (body: Schemas["PatchedTrainingPlanRequest"]) => Promise<TrainingPlan>
  remove: () => Promise<void>
  recommendations: () => Promise<Recommendation[]>
  addItem: (body: Schemas["PlanItemRequest"]) => Promise<TrainingPlan>
  updateItem: (id: string, body: PlanItemInput) => Promise<TrainingPlan>
  deleteItem: (id: string) => Promise<TrainingPlan>
}

export const personalPlanApi = (id: string): PlanApi => ({
  key: trainingKeys.plan(id),
  listKey: trainingKeys.plans,
  get: () => getPlan(id),
  update: (body) => updatePlan(id, body),
  remove: () => deletePlan(id),
  recommendations: () => listRecommendations(id),
  addItem: (body) => addPlanItem(id, body),
  updateItem: (item, body) => updatePlanItem(id, item, body),
  deleteItem: (item) => deletePlanItem(id, item),
})

export const clubPlanApi = (orgId: string, id: string): PlanApi => ({
  key: trainingKeys.clubPlan(orgId, id),
  listKey: trainingKeys.clubPlans(orgId),
  get: () => getClubPlan(orgId, id),
  update: (body) => updateClubPlan(orgId, id, body),
  remove: () => deleteClubPlan(orgId, id),
  recommendations: () => listClubRecommendations(orgId, id),
  addItem: (body) => addClubPlanItem(orgId, id, body),
  updateItem: (item, body) => updateClubPlanItem(orgId, id, item, body),
  deleteItem: (item) => deleteClubPlanItem(orgId, id, item),
})
