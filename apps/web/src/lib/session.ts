import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import type { User } from "@/lib/auth"

export const meQueryKey = ["auth", "me"] as const

export const getMe = () => api<User>("/auth/me/")

export function useMe() {
  return useQuery({ queryKey: meQueryKey, queryFn: getMe, retry: false, staleTime: 60_000 })
}

/**
 * Only same-app paths are allowed as destinations after login or signup (no open redirects). The same
 * rules as the API's ReturnPathField: browsers read a backslash as a slash, so "/\evil.example" would
 * leave the app, and whitespace or control characters have no place in a path.
 */
export function safeNext(next: string | null | undefined, fallback?: string): string
export function safeNext(next: string | null | undefined, fallback: null): string | null
export function safeNext(next: string | null | undefined, fallback: string | null = "/home"): string | null {
  const ok = !!next && next.length <= 300 && next.startsWith("/") && !next.startsWith("//") && !/[\\\s\p{Cc}]/u.test(next)
  return ok ? next : fallback
}
