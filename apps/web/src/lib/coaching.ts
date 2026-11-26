import { api, ApiError } from "@/lib/api"
import type { Schemas } from "@/lib/schema"
import type { PlanApi, Recommendation, TrainingPlan } from "@/lib/training"

// Coaching (REQ-047): coach profiles, coachings, bookings, trainees and coach's notes.
export type CoachProfile = Schemas["CoachProfile"]
export type CoachProfileInput = Schemas["CoachProfileRequest"]
export type CoachLevel = Schemas["CoachLevelEnum"]
export type Availability = Schemas["Availability"]
export type Coaching = Schemas["Coaching"]
export type Booking = Schemas["Booking"]
export type Slot = Schemas["Slot"]
export type CoachComment = Schemas["Comment"]
export type Trainee = Schemas["Trainee"]
export type TraineeMatch = Schemas["TraineeMatch"]
export type CalendarEntry = Schemas["CalendarEntry"]

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

export const BOOKING_STATUS_LABEL: Record<Booking["status"], string> = {
  requested: "Waiting for the coach",
  confirmed: "Confirmed",
  declined: "Declined",
  cancelled: "Cancelled",
  completed: "Done",
}

export const coachingKeys = {
  all: ["coaching"] as const,
  profile: ["coaching", "profile"] as const,
  coaches: (search: string) => ["coaching", "coaches", search] as const,
  coach: (id: string) => ["coaching", "coach", id] as const,
  slots: (id: string, minutes: number) => ["coaching", "slots", id, minutes] as const,
  coachings: ["coaching", "coachings"] as const,
  bookings: ["coaching", "bookings"] as const,
  pastBookings: ["coaching", "bookings", "past"] as const,
  trainee: (id: string) => ["coaching", "trainee", id] as const,
  traineePlan: (coachingId: string, planId: string) => ["coaching", "trainee", coachingId, "plan", planId] as const,
  calendar: (from: string, to: string) => ["coaching", "calendar", from, to] as const,
  notes: (kind: "personal" | "official", id: string) => ["coaching", "notes", kind, id] as const,
}

export const getMyCoachProfile = () => api<CoachProfile>("/me/coach-profile/")
/** The signed-in player's coach profile, or null when they don't coach (the API answers 404). */
export const getMyCoachProfileOrNull = () =>
  getMyCoachProfile().catch((error) => (error instanceof ApiError && error.status === 404 ? null : Promise.reject(error)))
/** Open the coach's organizing desk (made on first use) named after the coach or their firm. */
export const openCoachOrganizer = (presented_as: "coach" | "firm") =>
  api<Schemas["CoachOrganizer"]>("/me/coach-profile/organizer/", { body: { presented_as } })
export const saveCoachProfile = (body: Partial<CoachProfileInput>) => api<CoachProfile>("/me/coach-profile/", { method: "PUT", body })
export const saveAvailability = (windows: Schemas["AvailabilityRequest"][]) =>
  api<Availability[]>("/me/coach-availability/", { method: "PUT", body: { windows } })

export const listCoaches = (search: string) =>
  api<Schemas["PaginatedCoachProfileList"]>(`/coaches/?page_size=50${search ? `&search=${encodeURIComponent(search)}` : ""}`)
export const getCoach = (id: string) => api<CoachProfile>(`/coaches/${id}/`)
/** Rate a coach you trained with, 1 to 5 stars; null removes your rating. Answers the updated profile. */
export const rateCoach = (id: string, stars: number | null) =>
  stars == null ? api<CoachProfile>(`/coaches/${id}/rating/`, { method: "DELETE" }) : api<CoachProfile>(`/coaches/${id}/rating/`, { method: "PUT", body: { stars } })
export const listSlots = (id: string, minutes: number) => api<Slot[]>(`/coaches/${id}/slots/?days=14&minutes=${minutes}`)

export const listCoachings = () => api<Coaching[]>("/me/coachings/")
export const askCoach = (coachId: string, message: string) => api<Coaching>("/me/coachings/", { body: { coach_id: coachId, message } })
export const answerCoaching = (id: string, action: "accept" | "decline" | "end") =>
  api<Coaching>(`/me/coachings/${id}/${action}/`, { method: "POST" })

export const listBookings = () => api<Booking[]>("/me/bookings/")
/** Sessions that have ended, newest first. */
export const listPastBookings = () => api<Booking[]>("/me/bookings/?past=1")
export const bookSession = (body: Schemas["BookingRequestRequest"]) => api<Booking>("/me/bookings/", { body })
export const answerBooking = (id: string, action: "confirm" | "decline" | "cancel" | "complete", reason = "") =>
  api<Booking>(`/me/bookings/${id}/${action}/`, { body: { reason } })

export const getTrainee = (id: string) => api<Trainee>(`/me/trainees/${id}/`)
export const givePlan = (coachingId: string, body: Schemas["AssignPlanRequest"]) =>
  api<TrainingPlan>(`/me/trainees/${coachingId}/plans/`, { body })
export const commentOnMatch = (coachingId: string, body: Schemas["CommentInputRequest"]) =>
  api<CoachComment>(`/me/trainees/${coachingId}/comments/`, { body })
export const editComment = (id: string, body: string) => api<CoachComment>(`/me/coach-comments/${id}/`, { method: "PATCH", body: { body } })
export const deleteComment = (id: string) => api<void>(`/me/coach-comments/${id}/`, { method: "DELETE" })

export const listCoachNotes = (kind: "personal" | "official", id: string) =>
  api<CoachComment[]>(`/me/coach-notes/?${kind === "personal" ? "personal_match" : "match"}=${id}`)

export const getCalendar = (from: string, to: string) => api<CalendarEntry[]>(`/me/coach-calendar/?from=${from}&to=${to}`)

/** A plan the coach gave a trainee, edited with the same screen as the player's own plans. */
export const traineePlanApi = (coachingId: string, id: string): PlanApi => {
  const base = `/me/trainees/${coachingId}/plans/${id}`
  return {
    key: coachingKeys.traineePlan(coachingId, id),
    listKey: coachingKeys.trainee(coachingId),
    get: () => api<TrainingPlan>(`${base}/`),
    update: (body) => api<TrainingPlan>(`${base}/`, { method: "PATCH", body }),
    remove: () => api<void>(`${base}/`, { method: "DELETE" }),
    recommendations: () => api<Recommendation[]>(`${base}/recommendations/`),
    addItem: (body) => api<TrainingPlan>(`${base}/items/`, { body }),
    updateItem: (item, body) => api<TrainingPlan>(`${base}/items/${item}/`, { method: "PATCH", body }),
    deleteItem: (item) => api<TrainingPlan>(`${base}/items/${item}/`, { method: "DELETE" }),
  }
}

export function formatMoney(minor: number | null | undefined, currency: string) {
  if (minor == null) return ""
  return `${currency} ${(minor / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}

/** The first and last day (YYYY-MM-DD) of the week that holds `day`, Monday first. */
export function weekOf(day: Date) {
  const start = new Date(day)
  start.setDate(day.getDate() - ((day.getDay() + 6) % 7))
  const end = new Date(start)
  end.setDate(start.getDate() + 6)
  return { from: isoDay(start), to: isoDay(end) }
}

export function isoDay(day: Date) {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}
