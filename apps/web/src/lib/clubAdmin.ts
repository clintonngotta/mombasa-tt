import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { ApiError } from "@/lib/api"
import { clubKeys } from "@/lib/clubs"

/** Card row used by the club admin lists. */
export const ROW = "flex flex-wrap items-center gap-3 rounded-xl border bg-card p-4"

/**
 * The permissions behind these panels come from the cached membership list. If the server says 403, the
 * player's roles changed elsewhere: refresh memberships so the panels go away, and say why meanwhile.
 */
export function useAdminAccessLost(...errors: unknown[]) {
  const queryClient = useQueryClient()
  const lost = errors.some((error) => error instanceof ApiError && error.status === 403)
  useEffect(() => {
    if (lost) void queryClient.invalidateQueries({ queryKey: clubKeys.memberships })
  }, [lost, queryClient])
  return lost
}
