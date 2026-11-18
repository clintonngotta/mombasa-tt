import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"
import type { Config, Player, ScoreEvent, Side, State } from "@scoring"

export type Scorecard = Schemas["Scorecard"]
export type MyScorecard = Schemas["MyScorecard"]
export type ScoringSummary = Schemas["ScoringSummary"]
export type ScoringStatus = Schemas["ScoringStatusEnum"]
export type Umpire = Schemas["Umpire"]
export type SubmitResult = Schemas["SubmitResult"]

/** A score event on its way to the server: its own id (a retry is recognised) and its place in the stream. */
export type Envelope = { id: string; sequence: number; event: ScoreEvent; device_time: string; expected_revision?: number }

export const scoringKeys = {
  mine: ["scoring", "mine"] as const,
  card: (id: string) => ["scoring", "card", id] as const,
  umpires: (eventId: string) => ["scoring", "umpires", eventId] as const,
}

export const listMyScorecards = () => api<Schemas["PaginatedMyScorecardList"]>("/me/scorecards/")
export const getScorecard = (id: string) => api<Scorecard>(`/scorecards/${id}/`)
export const sendEvents = (id: string, assignmentId: string, events: Envelope[]) => api<SubmitResult>(`/scorecards/${id}/events/`, { body: { assignment_id: assignmentId, events } })
export const confirmScorecard = (card: Pick<Scorecard, "id" | "assignment_id" | "revision">) =>
  api<Scorecard>(`/scorecards/${card.id}/confirm/`, { body: { assignment_id: card.assignment_id, revision: card.revision } })

/** The most events the server takes in one request. */
export const MAX_BATCH = 200

/** The host's members who can be given a match to score; competition staff only. */
export const listUmpires = (tournamentId: string, eventId: string) => api<Umpire[]>(`/tournaments/${tournamentId}/events/${eventId}/umpires/`)
/** Assign the umpire of a match or of one rubber of a tie; `userId` null takes it back. */
export const assignUmpire = (tournamentId: string, eventId: string, matchId: string, userId: string | null, rubberId?: string) =>
  api<Schemas["MatchDetail"]>(`/tournaments/${tournamentId}/events/${eventId}/matches/${matchId}/umpire/`, { body: { user_id: userId, ...(rubberId ? { rubber_id: rubberId } : {}) } })

export const SCORING_STATUS_LABEL: Record<ScoringStatus, string> = {
  unassigned: "No umpire yet",
  assigned: "Umpire assigned",
  in_progress: "Being played",
  finished: "Played, waiting for the umpire to confirm",
  confirmed: "Result confirmed",
}

/** The engine's view of a sheet the API sent: same shapes, narrower types. */
export const configOf = (card: Pick<Scorecard, "config">) => card.config as Config
export const stateOf = (card: Pick<Scorecard, "state">) => card.state as unknown as State

/** What the rules refused, in the umpire's words. */
export const REFUSAL: Record<string, string> = {
  already_started: "The match has already started.",
  invalid_start: "Choose who serves and receives first, and the ends.",
  not_in_progress: "The match isn't being played, so nothing can be scored.",
  not_doubles: "Only a doubles pair chooses its first server.",
  game_under_way: "The first server can only be chosen before the first point of a game.",
  not_serving_pair: "Only the pair serving first chooses its server.",
  timeout_used: "That side has already taken its time-out.",
  nothing_to_undo: "There is nothing to undo.",
  sequence_gap: "Some points didn't reach the server in order.",
  sequence_conflict: "The server already holds a different action at that place.",
  revision_conflict: "The server holds less of this match than this device had seen.",
}

/** "2–1": the winner's games first. */
export function winnersScore(state: Pick<State, "winner" | "games_won">) {
  const [a, b] = state.games_won
  return state.winner === "b" ? `${b}–${a}` : `${a}–${b}`
}

/** Each finished game from the winner's side: "11–2, 0–11, 11–0". */
export const winnersGames = (state: Pick<State, "winner" | "games">) => state.games.map(([a, b]) => (state.winner === "b" ? `${b}–${a}` : `${a}–${b}`)).join(", ")

export type Names = Record<Player, string> & Record<Side, string>

/** Display names for each player slot and each side of a sheet. */
export function namesOf(card: Pick<Scorecard, "a" | "b">): Names {
  const names = { a: card.a.title, b: card.b.title } as Names
  for (const player of [...card.a.players, ...card.b.players]) names[player.slot] = player.display_name
  return names
}
