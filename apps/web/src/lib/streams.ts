import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// Watch links (REQ-042): where a tournament or one of its matches is streamed on another site.
export type LiveStream = Schemas["LiveStream"]
export type StreamReportReason = Schemas["StreamReportReasonEnum"]

export const REPORT_REASONS: { value: StreamReportReason; label: string }[] = [
  { value: "broken", label: "Doesn't work" },
  { value: "wrong", label: "Wrong match or event" },
  { value: "inappropriate", label: "Inappropriate or unsafe" },
  { value: "other", label: "Something else" },
]

export const streamKeys = {
  all: ["streams"] as const,
  of: (tournamentId: string, matchId?: string) => ["streams", tournamentId, matchId ?? ""] as const,
}

const base = (tournamentId: string) => `/tournaments/${tournamentId}/streams/`

export const listStreams = (tournamentId: string, matchId?: string) =>
  api<LiveStream[]>(matchId ? `${base(tournamentId)}?match=${encodeURIComponent(matchId)}` : base(tournamentId))
export const addStream = (tournamentId: string, body: Schemas["LiveStreamRequest"]) => api<LiveStream>(base(tournamentId), { body })
export const removeStream = (tournamentId: string, id: string) => api<void>(`${base(tournamentId)}${id}/`, { method: "DELETE" })
export const reportStream = (tournamentId: string, id: string, body: Schemas["ReportRequest"]) =>
  api<void>(`${base(tournamentId)}${id}/report/`, { body })

/** Same check as the API, so a mistyped link is caught before it is sent. */
export function streamUrlProblem(value: string): string | null {
  let url: URL
  try {
    url = new URL(value.trim())
  } catch {
    return "Paste the full link, starting with https://."
  }
  if (url.protocol !== "https:") return "Use a secure link: it starts with https://."
  if (url.username || url.password) return "A link can't carry a username or password."
  if (url.port && url.port !== "443") return "Use the site's usual address, without a port number."
  return null
}
