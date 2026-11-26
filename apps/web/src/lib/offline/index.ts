// Working without a connection (REQ-035). Screens a person has opened are saved on the device for
// their account and shown again offline. Changes they make offline are kept on the device and sent
// once the connection is back (lib/offline/store.ts).
import { useSyncExternalStore } from "react"
import { dehydrate, hydrate, type DehydratedState, type QueryClient, type QueryKey } from "@tanstack/react-query"
import { api, ApiError } from "@/lib/api"
import { APP_BUILD } from "@/lib/pwa"
import { OfflineStore, StorageError, type FlushResult, type Outcome, type PendingChange } from "@/lib/offline/store"

export type { PendingChange } from "@/lib/offline/store"

const ACCOUNT = "coast-tt-account"
/** Saved screens older than this are not shown: too likely to mislead. */
const SCREENS_MAX_AGE = 14 * 24 * 60 * 60 * 1000
const SYNC_EVERY = 30_000

/**
 * Query key roots that are never saved on the device: money, private notes, door takings, invitation
 * links, scoring, which has its own journal, push devices, which only mean anything live, and what is
 * near the player, which would give away where they were. These need a connection to open.
 */
const NOT_SAVED = new Set(["finance", "match-notes", "door", "coaching", "invitation", "scoring", "guests", "push", "nearby"])

let store: OfflineStore | null = null
function offlineStore(): OfflineStore | null {
  if (store) return store
  if (typeof indexedDB === "undefined") return null
  store = new OfflineStore(indexedDB)
  return store
}

// --- State the banner and the sync page show ------------------------------------------------------

export type SyncState = {
  online: boolean
  /** Waiting to be sent. */
  waiting: number
  /** The server wouldn't take them: they need the person's decision. */
  refused: number
  /** Sending stopped because the session ended: log in again as the same person to send. */
  signedOut: boolean
  syncing: boolean
  /** When the screens shown were saved, if they come from the device rather than the server. */
  savedAt: string | null
}

let state: SyncState = {
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  waiting: 0,
  refused: 0,
  signedOut: false,
  syncing: false,
  savedAt: null,
}
const listeners = new Set<() => void>()
function set(change: Partial<SyncState>) {
  state = { ...state, ...change }
  for (const listener of listeners) listener()
}
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
export function useSyncState(): SyncState {
  return useSyncExternalStore(subscribe, () => state)
}

/** Other tabs hear when the list of changes changes, so their counts stay right. */
const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("coast-tt-offline")
channel?.addEventListener("message", () => void recount())

export const lastAccount = () => localStorage.getItem(ACCOUNT)

async function recount() {
  const userId = lastAccount()
  const kept = userId ? await offlineStore()?.list(userId).catch(() => []) : []
  set({ waiting: kept?.filter((c) => c.state === "waiting").length ?? 0, refused: kept?.filter((c) => c.state === "refused").length ?? 0 })
}

export async function pendingChanges(): Promise<PendingChange[]> {
  const userId = lastAccount()
  if (!userId) return []
  return (await offlineStore()?.list(userId)) ?? []
}

function changed() {
  channel?.postMessage("changed")
  return recount()
}

// --- Making a change ----------------------------------------------------------------------------

export type Sent<T> = { kept: false; data: T } | { kept: true }

type ChangeRequest = {
  method?: PendingChange["method"]
  path: string
  body?: unknown
  /** What it does, in words: "Mark Amina present at the AGM". */
  label: string
  /** What to refresh once it is through. */
  refresh: QueryKey[]
}

const isNetworkError = (error: unknown) => error instanceof TypeError

/**
 * Send a change now, or keep it on the device if there is no connection. `{kept: true}` means it is
 * saved on the device and will be sent later; the screen should say so. A refusal from the server is
 * thrown as usual. If the device can't save it either, the network error is thrown: it wasn't saved.
 */
export async function sendOrKeep<T>(request: ChangeRequest): Promise<Sent<T>> {
  const userId = lastAccount()
  const change: PendingChange = {
    id: crypto.randomUUID(),
    userId: userId ?? "",
    method: request.method ?? "POST",
    path: request.path,
    body: request.body ?? {},
    label: request.label,
    refresh: request.refresh as unknown[][],
    createdAt: new Date().toISOString(),
    state: "waiting",
  }
  const keep = async (cause: unknown): Promise<Sent<T>> => {
    const kept = offlineStore()
    if (!userId || !kept) throw cause
    try {
      await kept.add(change)
    } catch (error) {
      throw error instanceof StorageError ? error : cause
    }
    await changed()
    if (navigator.onLine) void syncNow()
    return { kept: true }
  }
  // Changes made earlier go first: never let a later one overtake them.
  if (!navigator.onLine || state.waiting > 0) return keep(new TypeError("offline"))
  try {
    const data = await api<T>(change.path, { method: change.method, body: change.body, headers: { "Idempotency-Key": change.id } })
    return { kept: false, data }
  } catch (error) {
    // The request may have got through with its reply lost: the key makes sending it again safe.
    if (isNetworkError(error)) return keep(error)
    throw error
  }
}

// --- Sending what was kept ----------------------------------------------------------------------

let client: QueryClient | null = null

const send = async (change: PendingChange): Promise<Outcome> => {
  try {
    await api(change.path, { method: change.method, body: change.body, headers: { "Idempotency-Key": change.id } })
    return { kind: "sent" }
  } catch (error) {
    if (!(error instanceof ApiError)) return { kind: "later" }
    if (error.status === 401) return { kind: "stop", reason: "signed_out" }
    if (error.status === 426) return { kind: "stop", reason: "outdated" }
    if (error.status >= 500 || error.status === 429 || error.code === "request_in_progress") return { kind: "later" }
    return { kind: "refused", message: error.serverMessage ?? `Refused (${error.status}).`, code: error.code }
  }
}

let running: Promise<FlushResult | null> | null = null

/** Send the waiting changes now. One tab sends at a time; the others wait for it. */
export function syncNow(): Promise<FlushResult | null> {
  running ??= (async () => {
    const userId = lastAccount()
    const kept = offlineStore()
    if (!userId || !kept || !navigator.onLine) return null
    set({ syncing: true })
    try {
      const work = () => kept.flush(userId, send)
      const result = navigator.locks ? await navigator.locks.request("coast-tt-offline-sync", work) : await work()
      set({ signedOut: result.stopped === "signed_out" })
      if (result.sent.length > 0 && client) {
        for (const key of new Set(result.sent.flatMap((change) => change.refresh.map((k) => JSON.stringify(k))))) {
          void client.invalidateQueries({ queryKey: JSON.parse(key) as QueryKey })
        }
      }
      if (result.sent.length > 0 || result.refused > 0) channel?.postMessage("changed")
      return result
    } catch {
      return null
    } finally {
      await recount()
      set({ syncing: false })
      running = null
    }
  })()
  return running
}

export async function retryChange(id: string) {
  await offlineStore()?.retry(id, crypto.randomUUID())
  await changed()
  void syncNow()
}

export async function discardChange(id: string) {
  await offlineStore()?.remove(id)
  await changed()
}

/** Changes of any account still on this device: logging out or updating must not lose them. */
export async function changesOnDevice(): Promise<number> {
  return (await offlineStore()?.countAll().catch(() => 0)) ?? 0
}

/** Changes of this account still waiting or set aside. */
export async function unsentChanges(userId: string): Promise<number> {
  return ((await offlineStore()?.list(userId).catch(() => [])) ?? []).length
}

// --- Saving screens -----------------------------------------------------------------------------

const saveable = (key: QueryKey) => !NOT_SAVED.has(String(key[0]))

/**
 * Show the screens this device saved for the last account, before the first render, so the app opens
 * offline where it left off. Each screen still asks the server as usual when there is a connection.
 */
export async function restoreScreens(queryClient: QueryClient): Promise<void> {
  const userId = lastAccount()
  const kept = offlineStore()
  if (!userId || !kept) return
  try {
    const saved = await Promise.race([kept.loadScreens(userId), new Promise<undefined>((resolve) => setTimeout(resolve, 1500))])
    if (!saved || Date.now() - Date.parse(saved.savedAt) > SCREENS_MAX_AGE) return
    hydrate(queryClient, saved.state as DehydratedState)
    // Saved screens are shown at once but count as out of date, so each asks the server when it opens.
    void queryClient.invalidateQueries({ refetchType: "none" })
    set({ savedAt: saved.savedAt })
  } catch {
    // Nothing saved, or no storage: the app works online as before.
  }
}

/** The account now signed in, from /auth/me/. A different person's saved screens are removed. */
export function setAccount(userId: string | null) {
  if (!userId) return
  if (lastAccount() !== userId) {
    localStorage.setItem(ACCOUNT, userId)
    void recount()
  }
  void offlineStore()?.keepScreensOf(userId).catch(() => undefined)
}

/** Logging out: forget the account's saved screens and kept changes (after the person decided). */
export async function forgetAccount(userId: string) {
  await offlineStore()?.purge(userId).catch(() => undefined)
  if (lastAccount() === userId) localStorage.removeItem(ACCOUNT)
  set({ waiting: 0, refused: 0, savedAt: null, signedOut: false })
}

/** Start saving screens, and sending kept changes whenever the connection comes back. */
export function startOffline(queryClient: QueryClient) {
  client = queryClient
  let timer: number | undefined
  const save = () => {
    timer = undefined
    const userId = (queryClient.getQueryData(["auth", "me"]) as { id?: string } | undefined)?.id
    const kept = offlineStore()
    if (!userId || !kept || userId !== lastAccount()) return
    const saved = dehydrate(queryClient, {
      shouldDehydrateQuery: (query) => query.state.status === "success" && saveable(query.queryKey),
      shouldDehydrateMutation: () => false,
    })
    void kept.saveScreens({ userId, savedAt: new Date().toISOString(), build: APP_BUILD, state: saved }).catch(() => undefined)
  }
  queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || event.action.type !== "success") return
    const key = event.query.queryKey
    if (key[0] === "auth" && key[1] === "me") setAccount((event.query.state.data as { id?: string } | undefined)?.id ?? null)
    // Fresh from the server: what's shown no longer comes from the device.
    if (state.savedAt && navigator.onLine) set({ savedAt: null })
    timer ??= window.setTimeout(save, 2000)
  })

  window.addEventListener("online", () => {
    set({ online: true })
    void syncNow()
  })
  window.addEventListener("offline", () => set({ online: false }))
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void syncNow()
  })
  window.setInterval(() => {
    if (state.waiting > 0) void syncNow()
  }, SYNC_EVERY)
  void recount().then(() => syncNow())
}
