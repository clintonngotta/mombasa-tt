import { useMatch } from "react-router-dom"
import { api } from "@/lib/api"
import type { Schemas } from "@/lib/schema"

// One player in one tournament (TASK-148): their profile as the reader may see it, and their record there.
export type TournamentPlayer = Schemas["TournamentPlayer"]
export type PlayerEvent = Schemas["PlayerEvent"]
export type PlayerMatch = Schemas["PlayerMatch"]

export const tournamentPlayerKeys = {
  detail: (tournamentId: string, playerId: string) => ["tournaments", "detail", tournamentId, "player", playerId] as const,
}

export const getTournamentPlayer = (tournamentId: string, playerId: string) =>
  api<TournamentPlayer>(`/tournaments/${tournamentId}/players/${playerId}/`)

export const tournamentPlayerPath = (tournamentId: string, playerId: string) => `/tournaments/${tournamentId}/players/${playerId}`

/** Inside a tournament's pages, where a player's name leads; null elsewhere, where names stay text. */
export function usePlayerPath(): ((playerId: string) => string) | null {
  const match = useMatch("/tournaments/:id/*")
  const id = match?.params.id
  if (!id || id === "new") return null
  return (playerId) => tournamentPlayerPath(id, playerId)
}
