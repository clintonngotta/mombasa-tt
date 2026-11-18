import { api } from "@/lib/api"
import { can, type Membership } from "@/lib/clubs"
import { daysBetween, todayIn } from "@/lib/dates"
import type { Schemas } from "@/lib/schema"

export type Tournament = Schemas["Tournament"]
export type TournamentScope = Tournament["scope"]
export type TournamentStatus = Schemas["TournamentStatusEnum"]
export type TournamentInput = Schemas["TournamentRequest"]
export type TournamentEvent = Schemas["Event"]
export type EventAdmission = TournamentEvent["admission"]
export type EventStatus = Schemas["EventStatusEnum"]
export type EventKind = Schemas["EventKindEnum"]
export type EventFormat = Schemas["EventFormatEnum"]
export type Seeding = Schemas["SeedingEnum"]
export type BestOf = Schemas["BestOfEnum"]
/** One individual match of a team tie. */
export type RubberKind = Schemas["SinglesOrDoublesEnum"]

export const MAX_TIE_RUBBERS = 9
export const DEFAULT_TIE_RUBBERS: RubberKind[] = ["singles", "singles", "doubles", "singles", "singles"]

/** "5 rubbers (4 singles, 1 doubles), first to 3". */
export function tieSummary(rubbers: readonly RubberKind[], winsNeeded: number) {
  const doubles = rubbers.filter((kind) => kind === "doubles").length
  const singles = rubbers.length - doubles
  const mix = [singles ? `${singles} singles` : "", doubles ? `${doubles} doubles` : ""].filter(Boolean).join(", ")
  return `${rubbers.length} ${rubbers.length === 1 ? "rubber" : "rubbers"} (${mix}), first to ${winsNeeded}`
}
export type EventInput = Schemas["EventRequest"]
export type LifecycleEntry = Schemas["LifecycleEntry"]
export type Money = Schemas["Money"]
export type When = "upcoming" | "past"
export type TournamentAction = "publish" | "start" | "complete" | "approval/request"
export type EventAction = "start" | "complete"

export const SCOPE_LABEL: Record<TournamentScope, string> = {
  local: "Local",
  regional: "Regional",
  national: "National",
  international: "International",
}
export const SCOPE_OPTIONS = (Object.keys(SCOPE_LABEL) as TournamentScope[]).map((value) => ({ value, label: SCOPE_LABEL[value] }))
export const ADMISSION_LABEL: Record<EventAdmission, string> = { open: "Open admission", closed: "Organizer approval" }

export const tournamentKeys = {
  all: ["tournaments"] as const,
  list: (when: When, term: string, scope: TournamentScope | "") => ["tournaments", "list", when, term, scope] as const,
  hosted: (orgId: string) => ["tournaments", "hosted", orgId] as const,
  detail: (id: string) => ["tournaments", "detail", id] as const,
  history: (id: string) => ["tournaments", "history", id] as const,
}

const BASE = "/tournaments/"
const one = (id: string) => `${BASE}${id}/`
const event = (id: string, eventId: string) => `${one(id)}events/${eventId}/`

export const listTournaments = (when: When, term: string, scope: TournamentScope | "") =>
  api<Schemas["PaginatedTournamentList"]>(`${BASE}?${new URLSearchParams({ when, search: term, scope })}`)
/** Every tournament the organization hosts, drafts included; needs competitions.manage. */
export const listHostedTournaments = (orgId: string) => api<Schemas["PaginatedTournamentList"]>(`/organizations/${orgId}/tournaments/?page_size=100`)
export const getTournament = (id: string) => api<Tournament>(one(id))
export const createTournament = (orgId: string, body: TournamentInput) => api<Tournament>(`/organizations/${orgId}/tournaments/`, { body })
export const updateTournament = (id: string, body: Schemas["PatchedTournamentRequest"]) => api<Tournament>(one(id), { method: "PATCH", body })
export const deleteTournament = (id: string) => api<void>(one(id), { method: "DELETE" })
export const moveTournament = (id: string, action: TournamentAction) => api<Tournament>(`${one(id)}${action}/`, { body: {} })
export const rejectTournamentApproval = (id: string, reason: string) => api<Tournament>(`${one(id)}approval/reject/`, { body: { reason } })
export const cancelTournament = (id: string, reason: string) => api<Tournament>(`${one(id)}cancel/`, { body: { reason } })
export const getTournamentHistory = (id: string) => api<LifecycleEntry[]>(`${one(id)}history/`)

// Event changes reply with the whole tournament.
export const createEvent = (id: string, body: EventInput) => api<Tournament>(`${one(id)}events/`, { body })
export const updateEvent = (id: string, eventId: string, body: Schemas["PatchedEventRequest"]) =>
  api<Tournament>(event(id, eventId), { method: "PATCH", body })
export const deleteEvent = (id: string, eventId: string) => api<Tournament>(event(id, eventId), { method: "DELETE" })
export const moveEvent = (id: string, eventId: string, action: EventAction) => api<Tournament>(`${event(id, eventId)}${action}/`, { body: {} })
export const cancelEvent = (id: string, eventId: string, reason: string) => api<Tournament>(`${event(id, eventId)}cancel/`, { body: { reason } })

/** The four views every event has (REQ-010). */
export type EventTab = "brackets" | "groups" | "schedule" | "standings"

/** The tab an event opens on: the one that shows its first stage. */
export const firstTab = (format: EventFormat): EventTab => (format === "knockout" ? "brackets" : "groups")

export const eventTabPath = (tournamentId: string, eventId: string, tab: EventTab) => `/tournaments/${tournamentId}/events/${eventId}/${tab}`

export const STATUS_LABEL: Record<TournamentStatus, string> = {
  draft: "Draft",
  published: "Published",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
}

export const EVENT_STATUS_LABEL: Record<EventStatus, string> = {
  scheduled: "Not started",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
}

export const KIND_LABEL: Record<EventKind, string> = { singles: "Singles", doubles: "Doubles", team: "Teams" }

export const FORMAT_LABEL: Record<EventFormat, string> = {
  round_robin: "Round robin",
  knockout: "Knockout",
  groups_knockout: "Groups, then knockout",
}

export const SEEDING_LABEL: Record<Seeding, string> = { rating: "Seeded by rating", manual: "Seeded by staff", none: "Unseeded" }

export const ACTION_LABEL: Record<LifecycleEntry["action"], string> = {
  approval_requested: "Approval requested",
  approval_rejected: "Approval declined",
  published: "Published",
  updated: "Details changed",
  started: "Started",
  completed: "Completed",
  cancelled: "Cancelled",
  event_started: "Event started",
  event_completed: "Event completed",
  event_cancelled: "Event cancelled",
  event_removed: "Event removed",
}

/** Completed or cancelled: nothing about it changes any more. */
export const isClosed = (subject: { status: TournamentStatus | EventStatus }) => subject.status === "completed" || subject.status === "cancelled"

/** "KES 500" or "Free". Declared only: Coast TT takes no payments (REQ-008). */
export function formatFee(fee: Money) {
  if (fee.amount_minor === 0) return "Free"
  const amount = fee.amount_minor / 100
  return `${fee.currency} ${amount.toLocaleString("en-KE", { minimumFractionDigits: Number.isInteger(amount) ? 0 : 2 })}`
}

/** One line about how an event is played. */
export function eventSummary(e: TournamentEvent) {
  const parts = [KIND_LABEL[e.kind], FORMAT_LABEL[e.format], `best of ${e.best_of}`]
  if (e.kind === "team" && e.tie_wins_needed) parts.push(`ties of ${tieSummary(e.tie_rubbers, e.tie_wins_needed)}`)
  if (e.format === "groups_knockout" && e.group_count && e.qualifiers_per_group) {
    parts.push(`${e.group_count} groups, ${e.qualifiers_per_group} through from each`)
  }
  return parts.join(" · ")
}

/** "Starts in 12 days", "Starts tomorrow", "Day 2 of 3" — nothing once it is over. Days are the venue's. */
export function countdown(t: Pick<Tournament, "starts_on" | "ends_on" | "timezone" | "status">, now = new Date()) {
  if (isClosed(t)) return null
  const today = todayIn(t.timezone, now)
  const until = daysBetween(today, t.starts_on)
  if (until > 0) {
    // Started ahead of its first day: the status already says so.
    if (t.status === "in_progress") return null
    return until === 1 ? "Starts tomorrow" : `Starts in ${until} days`
  }
  const left = daysBetween(today, t.ends_on)
  if (left < 0) return null
  const length = daysBetween(t.starts_on, t.ends_on) + 1
  return length === 1 ? "Today" : `Day ${1 - until} of ${length}`
}

/** Whether this membership list lets the player run competitions for the tournament's host. The server
 * checks every request; this only decides which controls to offer. */
export const canManageTournament = (memberships: readonly Membership[], t: Pick<Tournament, "organization">) =>
  can(
    memberships.find((m) => m.organization.id === t.organization.id),
    "competitions.manage"
  )
