// Browser push (REQ-019, TASK-034): an optional copy of the inbox on this device's lock screen.
//
// Everything here is best effort. The inbox has every alert whether push is supported, refused,
// blocked or switched off, and nothing else in the app waits on it. The service worker (pwa/
// service-worker.js) shows the messages; the server only ever sends them encrypted for this browser.
import { api } from "@/lib/api"
import { isAppleMobile, isStandalone } from "@/lib/pwa"
import type { Schemas } from "@/lib/schema"

export type PushStatus = Schemas["PushStatus"]
export type PushDevice = Schemas["PushDevice"]

export const pushKeys = { status: ["push", "status"] as const }

export const getPushStatus = () => api<PushStatus>("/me/push/")
export const removePushDevice = (id: string) => api<PushStatus>(`/me/push/devices/${id}/`, { method: "DELETE" })

/** Why push can't be switched on here, or null when it can (permission aside). */
export type Blocker =
  | "unsupported" // the browser has no Push API (or no service worker: private window, development build)
  | "install" // iPhone and iPad: only an app added to the Home Screen gets push (iOS 16.4 and later)
  | "insecure" // push needs https

export function blocker(): Blocker | null {
  if (!window.isSecureContext) return "insecure"
  if (isAppleMobile() && !isStandalone()) return "install"
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported"
  return null
}

/** "default" (not asked yet), "granted" or "denied" (blocked in the browser's site settings). */
export const permission = (): NotificationPermission => ("Notification" in window ? Notification.permission : "denied")

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null
  // No worker is registered in development, and a blocked one never registers: don't wait for it.
  return (await navigator.serviceWorker.getRegistration("/")) ?? null
}

/** This browser's push subscription, if it has one. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (blocker()) return null
  const found = await registration()
  return (await found?.pushManager.getSubscription()) ?? null
}

/** "Chrome on Android", "Safari on iPhone": how the player tells their devices apart. */
export function deviceLabel(agent = navigator.userAgent): string {
  const browser = /Edg\//.test(agent)
    ? "Edge"
    : /SamsungBrowser/.test(agent)
      ? "Samsung Internet"
      : /Firefox\//.test(agent)
        ? "Firefox"
        : /OPR\//.test(agent)
          ? "Opera"
          : /Chrome\//.test(agent)
            ? "Chrome"
            : /Safari\//.test(agent)
              ? "Safari"
              : "Browser"
  const system = /Android/.test(agent)
    ? "Android"
    : /iPhone/.test(agent)
      ? "iPhone"
      : /iPad/.test(agent) || (/Macintosh/.test(agent) && navigator.maxTouchPoints > 1)
        ? "iPad"
        : /Windows/.test(agent)
          ? "Windows"
          : /Mac OS X/.test(agent)
            ? "Mac"
            : /CrOS/.test(agent)
              ? "ChromeOS"
              : /Linux/.test(agent)
                ? "Linux"
                : ""
  return system ? `${browser} on ${system}` : browser
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/")
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

const tell = (subscription: PushSubscription) =>
  api<PushStatus>("/me/push/subscribe/", { body: { ...subscription.toJSON(), label: deviceLabel() } })

export type EnableResult = { status: PushStatus } | { refused: "denied" | "dismissed" | "unavailable" }

/**
 * Ask for permission (call from a tap: browsers ignore the request otherwise), subscribe this browser
 * with the server's key and register it for the signed-in player.
 */
export async function enablePush(publicKey: string): Promise<EnableResult> {
  if (blocker()) return { refused: "unavailable" }
  const answer = await Notification.requestPermission()
  if (answer !== "granted") return { refused: answer === "denied" ? "denied" : "dismissed" }
  const found = await registration()
  if (!found) return { refused: "unavailable" }
  let subscription = await found.pushManager.getSubscription()
  // A subscription made with another server key (the key was changed) can't be used: start again.
  const key = subscription?.options.applicationServerKey
  if (subscription && key && !sameKey(new Uint8Array(key), keyBytes(publicKey))) {
    await subscription.unsubscribe()
    subscription = null
  }
  subscription ??= await found.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) })
  return { status: await tell(subscription) }
}

const sameKey = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((value, i) => value === b[i])

/** Stop push on this browser, for this player. */
export async function disablePush(): Promise<PushStatus | null> {
  const subscription = await currentSubscription()
  if (!subscription) return null
  const endpoint = subscription.endpoint
  await subscription.unsubscribe().catch(() => false)
  return api<PushStatus>("/me/push/unsubscribe/", { body: { endpoint } })
}

/**
 * Before logging out: stop this browser getting the player's alerts, so the next person to use it
 * doesn't see them. Never holds up logging out for long, and never fails it.
 */
export async function forgetThisDevice(): Promise<void> {
  const attempt = disablePush().catch(() => null)
  await Promise.race([attempt, new Promise((done) => setTimeout(done, 3000))])
}

/**
 * On opening the app signed in: a browser already subscribed tells the server again, so its keys stay
 * current and, on a shared device, it belongs to whoever is signed in now. Quiet on any failure.
 */
export async function syncThisDevice(): Promise<void> {
  try {
    if (permission() !== "granted") return
    const subscription = await currentSubscription()
    if (subscription) await tell(subscription)
  } catch {
    // push is optional: the inbox has everything
  }
}
