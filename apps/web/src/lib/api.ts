import type { Schemas } from "@/lib/schema"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1"

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API request failed with ${status}`)
    this.status = status
    this.body = body
  }

  private get error(): Partial<ApiErrorBody> {
    return typeof this.body === "object" && this.body !== null ? (this.body as Partial<ApiErrorBody>) : {}
  }

  /** Stable machine-readable code, e.g. "invalid_credentials" or "email_unverified". */
  get code(): string | undefined {
    return this.error.code
  }

  get serverMessage(): string | undefined {
    return this.error.message
  }

  fieldErrors(): Record<string, string> {
    return this.error.fields ?? {}
  }
}

/** Error envelope returned by every API error (spec REQ-032). */
type ApiErrorBody = Schemas["ApiError"]

function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : undefined
}

async function ensureCsrfToken() {
  const existing = csrfToken()
  if (existing) return existing
  await fetch(`${API_BASE}/auth/csrf/`, { credentials: "include" })
  return csrfToken()
}

// Session cookies are HttpOnly (REQ-003); unsafe methods carry Django's CSRF header.
export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? (init.body === undefined ? "GET" : "POST")
  const headers: Record<string, string> = { Accept: "application/json" }
  if (init.body !== undefined) headers["Content-Type"] = "application/json"
  if (method !== "GET") {
    const token = await ensureCsrfToken()
    if (token) headers["X-CSRFToken"] = token
  }

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
    if (error.serverMessage) return error.serverMessage
  }
  return fallback
}
