const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1"

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with ${status}`)
    this.status = status
    this.body = body
  }

  /** DRF-style `{ field: ["message"] }` validation errors. */
  fieldErrors(): Record<string, string> {
    if (this.status !== 400 || typeof this.body !== "object" || this.body === null) return {}
    return Object.fromEntries(
      Object.entries(this.body).map(([field, value]) => [field, Array.isArray(value) ? String(value[0]) : String(value)])
    )
  }
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : undefined
}

// Session cookies are HttpOnly (REQ-003); unsafe methods carry Django's CSRF header.
export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? (init.body === undefined ? "GET" : "POST")
  const headers: Record<string, string> = { Accept: "application/json" }
  if (init.body !== undefined) headers["Content-Type"] = "application/json"
  const token = csrfToken()
  if (token && method !== "GET") headers["X-CSRFToken"] = token

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  })

  if (res.status === 204) return null as T
  const isJson = res.headers.get("content-type")?.includes("application/json")
  const data: unknown = isJson ? await res.json().catch(() => null) : null
  // A non-JSON reply means we reached something other than the API (proxy page, dev server).
  if (!isJson) throw new ApiError(502, null)
  if (!res.ok) throw new ApiError(res.status, data)
  return data as T
}

export function errorMessage(error: unknown, fallback = "Something went wrong. Please try again.") {
  if (error instanceof TypeError) return "Can't reach mombasa-tt right now. Check your connection and try again."
  if (error instanceof ApiError) {
    if (error.status === 429) return "Too many attempts. Wait a few minutes and try again."
    if (error.status >= 500) return "mombasa-tt is unavailable right now. Please try again shortly."
    const detail = (error.body as { detail?: unknown } | null)?.detail
    if (typeof detail === "string") return detail
  }
  return fallback
}
