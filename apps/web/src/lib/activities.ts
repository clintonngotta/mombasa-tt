import { api, apiUrl } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

export type Activity = Schemas["ClubActivity"]
export type ActivityInput = Schemas["ClubActivityRequest"]
export type Attendee = Schemas["Attendee"]
export type ScheduleItem = Schemas["ScheduleItem"]
export type Answer = Schemas["RsvpAnswerEnum"]
export type When = "upcoming" | "past"
export type ScheduleKind = ScheduleItem["kind"]

const base = (orgId: string) => `/organizations/${orgId}/activities/`

export const activityKeys = {
  all: ["activities"] as const,
  list: (orgId: string, when: When) => ["activities", orgId, "list", when] as const,
  detail: (orgId: string, id: string) => ["activities", orgId, "detail", id] as const,
  attendees: (orgId: string, id: string) => ["activities", orgId, "attendees", id] as const,
  invitees: (orgId: string, id: string) => ["activities", orgId, "invitees", id] as const,
  schedule: (orgId: string, when: When, kinds: ScheduleKind[]) => ["activities", orgId, "schedule", when, kinds] as const,
  myEvents: ["activities", "me", "events"] as const,
}

export const listActivities = (orgId: string, when: When) => api<Schemas["PaginatedClubActivityList"]>(`${base(orgId)}?when=${when}&page_size=50`)
export const getActivity = (orgId: string, id: string) => api<Activity>(`${base(orgId)}${id}/`)
export const createActivity = (orgId: string, body: ActivityInput) => api<Activity>(base(orgId), { body })
export const updateActivity = (orgId: string, id: string, body: Partial<ActivityInput>) => api<Activity>(`${base(orgId)}${id}/`, { method: "PATCH", body })
export const publishActivity = (orgId: string, id: string) => api<Activity>(`${base(orgId)}${id}/publish/`, { body: {} })
export const cancelActivity = (orgId: string, id: string, reason: string) => api<Activity>(`${base(orgId)}${id}/cancel/`, { body: { reason } })
export const answerActivity = (orgId: string, id: string, answer: Answer) => api<Activity>(`${base(orgId)}${id}/rsvp/`, { body: { answer } })
export const shareActivityCost = (orgId: string, id: string, body: Schemas["ShareCostRequest"]) => api<Activity>(`${base(orgId)}${id}/cost-share/`, { body })
export const listAttendees = (orgId: string, id: string) => api<Attendee[]>(`${base(orgId)}${id}/attendees/`)
// Events beyond the membership (REQ-046): check-in while it runs, attendance marked by staff, and the
// events that invite you (named, as a representative, or open to all players).
export const checkInActivity = (orgId: string, id: string) => api<Activity>(`${base(orgId)}${id}/check-in/`, { body: {} })
export const markActivityAttendance = (orgId: string, id: string, rsvp: string, attended: boolean) => api<Attendee>(`${base(orgId)}${id}/attendance/`, { body: { rsvp, attended } })
export const listMyEvents = () => api<Activity[]>("/me/events/")
export const listInvitees = (orgId: string, id: string) => api<{ invitee_ids: string[] }>(`${base(orgId)}${id}/invitees/`)

const scheduleQuery = (when: When, kinds: ScheduleKind[]) => {
  const params = new URLSearchParams({ when })
  for (const kind of kinds) params.append("kind", kind)
  return params.toString()
}
export const getSchedule = (orgId: string, when: When, kinds: ScheduleKind[]) => api<ScheduleItem[]>(`/organizations/${orgId}/schedule/?${scheduleQuery(when, kinds)}`)
export const scheduleCalendarUrl = (orgId: string, when: When, kinds: ScheduleKind[]) => apiUrl(`/organizations/${orgId}/schedule.ics?${scheduleQuery(when, kinds)}`)

export const KIND_LABEL: Record<Activity["kind"], string> = {
  social: "Social night",
  fun_day: "Fun day",
  visit: "Group visit",
  meeting: "Meeting",
  practice: "Practice night",
  open_day: "Open day",
  anniversary: "Anniversary",
  workshop: "Workshop",
  clinic: "Coaching clinic",
  awards: "Award night",
  other: "Other",
}
export const ANSWER_LABEL: Record<Answer, string> = { going: "Going", maybe: "Maybe", not_going: "Not going" }
export type Audience = NonNullable<Activity["audience"]>
export const AUDIENCE_LABEL: Record<Audience, string> = {
  members: "All members",
  selected: "Selected members",
  reps: "Representatives of clubs",
  named: "People I name",
  open: "Every player on Coast TT",
}
/** Who a published activity reaches, for the publish button and the organizer's summary. */
export const AUDIENCE_REACH: Record<Audience, string> = {
  members: "all members",
  selected: "the members invited",
  reps: "the representatives invited",
  named: "the people named",
  open: "every player",
}
