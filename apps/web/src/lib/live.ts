import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { drawKeys } from "@/lib/draws"
import { reservationKeys } from "@/lib/reservations"
import { scoringKeys } from "@/lib/scoring"
import { tournamentKeys } from "@/lib/tournaments"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1"
const MAX_WAIT = 30_000

type Changed = { type: "changed"; topic: "scores" | "results"; event: string | null }

/** The WebSocket address of a tournament's live updates, on the API's host (same origin in development). */
function socketUrl(tournamentId: string) {
  const base = new URL(API_BASE, window.location.href)
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:"
  return `${base.toString().replace(/\/$/, "")}/ws/tournaments/${tournamentId}/`
}

/** Refetches a tournament's scores, draws, standings and dispatch board as soon as the server says they changed.
 * The message carries no data: what the page shows still comes from the API with the viewer's permissions. Pages
 * keep their own refetch timers, so a dropped connection only makes updates slower. Reconnects with backoff. */
export function useLiveTournament(tournamentId: string | undefined) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!tournamentId || typeof WebSocket === "undefined") return
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let wait = 1000
    let stopped = false

    const refresh = (message: Changed) => {
      const stale: (readonly string[])[] = [scoringKeys.overview(tournamentId), tournamentKeys.detail(tournamentId), [...drawKeys.all, "match"]]
      if (message.event) stale.push(drawKeys.event(message.event), drawKeys.standings(message.event))
      // A result frees its table and players on the dispatch board.
      if (message.topic === "results") stale.push(reservationKeys.board(tournamentId))
      for (const queryKey of stale) void queryClient.invalidateQueries({ queryKey })
    }

    const open = () => {
      socket = new WebSocket(socketUrl(tournamentId))
      socket.onopen = () => {
        wait = 1000
      }
      socket.onmessage = (frame) => {
        try {
          const message = JSON.parse(String(frame.data)) as Changed
          if (message.type === "changed") refresh(message)
        } catch {
          // Not a message of ours: ignore it.
        }
      }
      socket.onclose = (closed) => {
        // 4401 signed out, 4404 not visible: asking again won't change the answer.
        if (stopped || closed.code === 4401 || closed.code === 4404) return
        retry = setTimeout(open, wait)
        wait = Math.min(wait * 2, MAX_WAIT)
      }
    }

    open()
    return () => {
      stopped = true
      clearTimeout(retry)
      socket?.close()
    }
  }, [tournamentId, queryClient])
}
