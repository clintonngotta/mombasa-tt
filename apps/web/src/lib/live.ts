import { useEffect, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { drawKeys } from "@/lib/draws"
import { controlKeys, reservationKeys } from "@/lib/reservations"
import type { Schemas } from "@/lib/schema"
import { scoringKeys } from "@/lib/scoring"
import { tournamentKeys } from "@/lib/tournaments"

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1"
const MAX_WAIT = 30_000
const LIST_EVERY = 1_000
/** How often a live view asks again when the socket is down: the polling fallback (REQ-043). */
export const POLL_WHILE_OFFLINE = 5_000

export type LiveMatch = Schemas["LiveMatch"]
export type MatchScore = Schemas["MatchScore"]
export type LiveCard = Schemas["LiveCard"]

export const liveKeys = {
  matches: (tournamentId: string) => ["live", tournamentId] as const,
}

/** The tournament's matches being scored now, as anybody who may see the tournament watches them. */
export const getLive = (tournamentId: string) => api<LiveMatch[]>(`/tournaments/${tournamentId}/live/`)

type Changed = { type: "changed"; topic: "scores" | "results" | "board"; event: string | null; match?: string | null }

/** The WebSocket address of a tournament's live updates, on the API's host (same origin in development). */
function socketUrl(tournamentId: string) {
  const base = new URL(API_BASE, window.location.href)
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:"
  return `${base.toString().replace(/\/$/, "")}/ws/tournaments/${tournamentId}/`
}

/** What a message makes stale. A score names its match, so pages showing other matches keep what they have. */
function staleKeys(tournamentId: string, message: Changed): (readonly string[])[] {
  const stale: (readonly string[])[] = [liveKeys.matches(tournamentId), scoringKeys.overview(tournamentId)]
  if (message.topic === "scores" && message.match) {
    // The board shows each table's score and the draw marks the match live; standings change only with a result.
    stale.push(drawKeys.match(message.match), reservationKeys.board(tournamentId), tournamentKeys.dashboard(tournamentId))
    if (message.event) stale.push(drawKeys.event(message.event))
    return stale
  }
  stale.push(tournamentKeys.detail(tournamentId), tournamentKeys.dashboard(tournamentId), [...drawKeys.all, "match"])
  if (message.event) stale.push(drawKeys.event(message.event), drawKeys.standings(message.event))
  // A result frees its table and players on the dispatch board; "board" is a change to the board itself.
  if (message.topic === "results" || message.topic === "board") stale.push(reservationKeys.board(tournamentId), controlKeys.desk(tournamentId), controlKeys.log(tournamentId))
  return stale
}

/**
 * Refetches what a tournament's pages show as soon as the server says it changed. The message carries no data:
 * what the page shows still comes from the API with the viewer's permissions. Reconnects with backoff. Returns
 * whether the socket is open, so live views poll instead while it isn't (`refetchInterval: pollUnless(open)`).
 */
export function useLiveTournament(tournamentId: string | undefined): boolean {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!tournamentId || typeof WebSocket === "undefined") return
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let wait = 1000
    let stopped = false
    let dropped = false

    // Points at several tables come close together: the live list is fetched again at most once a second.
    let listDue: ReturnType<typeof setTimeout> | undefined
    const listKey = liveKeys.matches(tournamentId)
    const refresh = (message: Changed) => {
      for (const queryKey of staleKeys(tournamentId, message)) {
        if (queryKey.join() === listKey.join()) {
          listDue ??= setTimeout(() => {
            listDue = undefined
            void queryClient.invalidateQueries({ queryKey: listKey })
          }, LIST_EVERY)
          continue
        }
        void queryClient.invalidateQueries({ queryKey })
      }
    }

    const connect = () => {
      socket = new WebSocket(socketUrl(tournamentId))
      socket.onopen = () => {
        wait = 1000
        setOpen(true)
        // Back after a drop: whatever changed meanwhile is fetched now.
        if (dropped) refresh({ type: "changed", topic: "results", event: null })
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
        setOpen(false)
        dropped = true
        // 4401 signed out, 4404 not visible: asking again won't change the answer.
        if (stopped || closed.code === 4401 || closed.code === 4404) return
        retry = setTimeout(connect, wait)
        wait = Math.min(wait * 2, MAX_WAIT)
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(retry)
      clearTimeout(listDue)
      socket?.close()
    }
  }, [tournamentId, queryClient])
  return open
}

/** A live view's refetch timer: none while the socket brings changes, every few seconds while it can't. */
export const pollUnless = (socketOpen: boolean) => (socketOpen ? false : POLL_WHILE_OFFLINE)
