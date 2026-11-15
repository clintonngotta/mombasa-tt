import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { User } from "@/lib/auth"

export const meQueryKey = ["auth", "me"] as const

export const getMe = () => api<User>("/auth/me/")

export function useMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: getMe, retry: false, staleTime: 60_000 })
}

/** Only same-app paths are allowed as post-login destinations (no open redirects). */
export function safeNext(next: string | null | undefined, fallback = "/home") {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : fallback
}
