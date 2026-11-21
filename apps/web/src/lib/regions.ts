import { api } from "@/lib/api"
import { sendOrKeep } from "@/lib/offline"
import type { Schemas } from "@/lib/schema"

// Regional bodies (REQ-048): the region's clubs, yearly agenda, articles, meetings and sponsorships.
export type RegionClub = Schemas["RegionClub"]
export type AgendaItem = Schemas["AgendaItem"]
export type AgendaKind = Schemas["AgendaItemKindEnum"]
export type Article = Schemas["Article"]
export type Meeting = Schemas["Meeting"]
export type MeetingAudience = Schemas["MeetingAudienceEnum"]
export type MeetingKind = Schemas["MeetingKindEnum"]
export type Sponsorship = Schemas["Sponsorship"]
export type Sponsor = Schemas["Sponsor"]

export const AGENDA_KIND_LABEL: Record<AgendaKind, string> = {
  tournament: "Tournament",
  meeting: "Meeting",
  event: "Event",
  deadline: "Deadline",
  other: "Other",
}

export const MEETING_KIND_LABEL: Record<MeetingKind, string> = {
  committee: "Committee",
  general: "General meeting",
  representatives: "Clubs' representatives",
  special: "Special meeting",
}

export const AUDIENCE_LABEL: Record<MeetingAudience, string> = {
  committee: "The committee",
  club_admins: "The admins of the region's clubs",
  members: "All members",
  named: "People I name",
}

export const regionKeys = {
  all: ["region"] as const,
  clubs: (orgId: string) => ["region", "clubs", orgId] as const,
  agenda: (orgId: string, year: number) => ["region", "agenda", orgId, year] as const,
  articles: (orgId: string) => ["region", "articles", orgId] as const,
  article: (orgId: string, id: string) => ["region", "article", orgId, id] as const,
  meetings: (orgId: string) => ["region", "meetings", orgId] as const,
  meeting: (orgId: string, id: string) => ["region", "meeting", orgId, id] as const,
  sponsorships: (orgId: string) => ["region", "sponsorships", orgId] as const,
  sponsors: (tournamentId: string) => ["region", "sponsors", tournamentId] as const,
  offers: (tournamentId: string) => ["region", "offers", tournamentId] as const,
  myAgenda: ["region", "me", "agenda"] as const,
  myArticles: ["region", "me", "articles"] as const,
  myMeetings: ["region", "me", "meetings"] as const,
}

const org = (orgId: string) => `/organizations/${orgId}`

export const listRegionClubs = (orgId: string) => api<RegionClub[]>(`${org(orgId)}/region-clubs/`)

export const listAgenda = (orgId: string, year: number) => api<AgendaItem[]>(`${org(orgId)}/agenda/?year=${year}`)
export const addAgendaItem = (orgId: string, body: Schemas["AgendaItemRequest"]) => api<AgendaItem>(`${org(orgId)}/agenda/`, { body })
export const deleteAgendaItem = (orgId: string, id: string) => api<void>(`${org(orgId)}/agenda/${id}/`, { method: "DELETE" })

export const listArticles = (orgId: string) => api<Article[]>(`${org(orgId)}/articles/`)
export const getArticle = (orgId: string, id: string) => api<Article>(`${org(orgId)}/articles/${id}/`)
export const createArticle = (orgId: string, body: Schemas["ArticleRequest"]) => api<Article>(`${org(orgId)}/articles/`, { body })
export const publishArticle = (orgId: string, id: string) => api<Article>(`${org(orgId)}/articles/${id}/publish/`, { method: "POST" })
export const deleteArticle = (orgId: string, id: string) => api<void>(`${org(orgId)}/articles/${id}/`, { method: "DELETE" })

export const listMeetings = (orgId: string) => api<Meeting[]>(`${org(orgId)}/meetings/`)
export const getMeeting = (orgId: string, id: string) => api<Meeting>(`${org(orgId)}/meetings/${id}/`)
export const createMeeting = (orgId: string, body: Schemas["MeetingRequest"]) => api<Meeting>(`${org(orgId)}/meetings/`, { body })
export const deleteMeeting = (orgId: string, id: string) => api<void>(`${org(orgId)}/meetings/${id}/`, { method: "DELETE" })
export const meetingAction = (orgId: string, id: string, action: "publish" | "check-in") =>
  api<Meeting>(`${org(orgId)}/meetings/${id}/${action}/`, { method: "POST" })
export const cancelMeeting = (orgId: string, id: string, reason: string) => api<Meeting>(`${org(orgId)}/meetings/${id}/cancel/`, { body: { reason } })
export const answerMeeting = (orgId: string, id: string, answer: "attending" | "apologies") =>
  api<Meeting>(`${org(orgId)}/meetings/${id}/answer/`, { body: { answer } })
export const recordMinutes = (orgId: string, id: string, minutes: string) => api<Meeting>(`${org(orgId)}/meetings/${id}/minutes/`, { body: { minutes } })

// Meeting rules and penalties (REQ-046): the secretary or governance staff take attendance and issue the
// penalties the rules set once the meeting is over; only the host's admin changes one after that.
export type Penalized = Schemas["PenalizedAttendanceEnum"]
export type AttendanceMark = Schemas["AttendanceMarkEnum"]
export type MeetingPenalty = Schemas["Penalty"]
export type MeetingInvitee = Schemas["Invitee"]
export const PENALIZED: Penalized[] = ["absent", "late", "apologies"]
export const ATTENDANCE_LABEL: Record<AttendanceMark, string> = { present: "Present", late: "Late", apologies: "Apologies", absent: "Absent" }
export const RULE_LABEL: Record<Penalized, string> = { absent: "Absent without apologies", late: "Arriving late", apologies: "Sending apologies" }
export const PENALTY_STATUS_LABEL: Record<MeetingPenalty["status"], string> = { issued: "Issued", waived: "Waived", paid: "Paid" }
export const markAttendance = (orgId: string, id: string, invitee: string, attendance: AttendanceMark) =>
  api<Meeting>(`${org(orgId)}/meetings/${id}/attendance/`, { body: { invitee, attendance } })
export const issuePenalties = (orgId: string, id: string) => api<Meeting>(`${org(orgId)}/meetings/${id}/penalties/`, { method: "POST" })
export const updatePenalty = (orgId: string, id: string, penaltyId: string, body: Schemas["PatchedPenaltyUpdateRequest"]) =>
  api<MeetingPenalty>(`${org(orgId)}/meetings/${id}/penalties/${penaltyId}/`, { method: "PATCH", body })

export const listSponsorships = (orgId: string) => api<Sponsorship[]>(`${org(orgId)}/sponsorships/`)
export const offerSponsorship = (orgId: string, body: Schemas["SponsorshipRequest"]) => api<Sponsorship>(`${org(orgId)}/sponsorships/`, { body })
export const withdrawSponsorship = (orgId: string, id: string) => api<Sponsorship>(`${org(orgId)}/sponsorships/${id}/withdraw/`, { body: { reason: "" } })

export const listSponsors = (tournamentId: string) => api<Sponsor[]>(`/tournaments/${tournamentId}/sponsors/`)
export const listOffers = (tournamentId: string) => api<Sponsorship[]>(`/tournaments/${tournamentId}/sponsorships/`)
export const decideOffer = (tournamentId: string, id: string, action: "accept" | "decline") =>
  api<Sponsorship>(`/tournaments/${tournamentId}/sponsorships/${id}/${action}/`, { body: { reason: "" } })

export const listMyAgenda = () => api<AgendaItem[]>("/me/agenda/")
export const listMyArticles = () => api<Article[]>("/me/articles/")
export const listMyMeetings = () => api<Meeting[]>("/me/meetings/")

/** "KES 50,000 · 72 Balls · 2 Trophies" */
export function describeSponsorship(offer: { amount_minor?: number | null; currency?: string; in_kind?: { item: string; quantity: number }[] }) {
  const parts = []
  if (offer.amount_minor) parts.push(`${offer.currency ?? "KES"} ${(offer.amount_minor / 100).toLocaleString("en-KE")}`)
  for (const goods of offer.in_kind ?? []) parts.push(`${goods.quantity} × ${goods.item}`)
  return parts.join(" · ")
}

// Offline (REQ-035): checking in and taking attendance happen in the room, where the connection may
// drop. These keep the change on the device and send it later when there is no connection.
export const checkInOrKeep = (orgId: string, meeting: Pick<Meeting, "id" | "title">) =>
  sendOrKeep<Meeting>({ path: `${org(orgId)}/meetings/${meeting.id}/check-in/`, label: `Check in to ${meeting.title}`, refresh: [regionKeys.all] })
export const markAttendanceOrKeep = (orgId: string, meeting: Pick<Meeting, "id" | "title">, invitee: Pick<MeetingInvitee, "id" | "display_name">, attendance: AttendanceMark) =>
  sendOrKeep<Meeting>({
    path: `${org(orgId)}/meetings/${meeting.id}/attendance/`,
    body: { invitee: invitee.id, attendance },
    label: `Mark ${invitee.display_name} ${ATTENDANCE_LABEL[attendance].toLowerCase()} at ${meeting.title}`,
    refresh: [regionKeys.all],
  })
