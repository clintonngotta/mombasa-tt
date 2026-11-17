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

/** Full address of a path the API hands out (e.g. a signed attachment link, which starts at the API's root). */
export function apiOriginUrl(path: string) {
  return /^https?:/.test(API_BASE) ? new URL(path, API_BASE).toString() : path
}

// Session cookies are HttpOnly (REQ-003); unsafe methods carry Django's CSRF header.
// A FormData body is sent as a file upload; anything else as JSON.
export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? (init.body === undefined ? "GET" : "POST")
  const headers: Record<string, string> = { Accept: "application/json" }
  const upload = init.body instanceof FormData
  if (init.body !== undefined && !upload) headers["Content-Type"] = "application/json"
  if (method !== "GET") {
    const token = await ensureCsrfToken()
    if (token) headers["X-CSRFToken"] = token
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: init.body === undefined ? undefined : upload ? (init.body as FormData) : JSON.stringify(init.body),
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
  if (error instanceof TypeError) return "Can't reach Coast TT right now. Check your connection and try again."
  if (error instanceof ApiError) {
    if (error.status === 429) return "Too many requests for now. Wait a while and try again."
    if (error.status >= 500) return "Coast TT is unavailable right now. Please try again shortly."
    if (error.serverMessage) return error.serverMessage
  }
  return fallback
}
