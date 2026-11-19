// The installed app (REQ-035): the service worker, a safe update and help to install.
//
// A new release's worker installs in the background and then waits. The page offers "Update" and
// switches only when nothing would be lost: no match is open on the deck in any tab and no score action
// of any account is waiting to be sent. The journal is never cleared by an update; a release that
// changes its layout migrates it (lib/deck/journal.ts).
import { useSyncExternalStore } from "react"

export type UpdateState = {
  /** A new version is installed and waiting for this page to switch to it. */
  waiting: boolean
  /** The API no longer serves this version: it has to update before it can go on. */
  outdated: boolean
  /** Another tab switched to the new version: this one runs the old one until it is reloaded. */
  switchedElsewhere: boolean
  /** The browser can install the app from a button (Chrome, Edge, Samsung Internet on Android). */
  installable: boolean
}

export type UpdateBlocker = { scoring: number; unsent: number }

type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> }

let state: UpdateState = { waiting: false, outdated: false, switchedElsewhere: false, installable: false }
const listeners = new Set<() => void>()
let registration: ServiceWorkerRegistration | null = null
let installPrompt: InstallPrompt | null = null
let switching = false

function set(change: Partial<UpdateState>) {
  state = { ...state, ...change }
  for (const listener of listeners) listener()
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useAppUpdate(): UpdateState {
  return useSyncExternalStore(subscribe, () => state)
}

/** The API said this build is too old (426 client_outdated). Called by lib/api. */
export function markOutdated() {
  if (!state.outdated) set({ outdated: true })
}

/** This release's build number, sent to the API with every request. */
export const APP_BUILD = __APP_BUILD__

/** Start the service worker. Production builds only: in development every file changes all the time. */
export function startServiceWorker() {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault()
    installPrompt = event as InstallPrompt
    set({ installable: true })
  })
  window.addEventListener("appinstalled", () => {
    installPrompt = null
    set({ installable: false })
  })
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    // The tab that asked reloads into the new version; any other tab carries on and offers a reload.
    if (switching) window.location.reload()
    else set({ switchedElsewhere: true, waiting: false })
  })
  const check = () => void registration?.update().catch(() => undefined)
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(
      (found) => {
        registration = found
        watch(found)
        // Look for a new release every hour and whenever the app comes back to the front.
        window.setInterval(check, 60 * 60 * 1000)
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible") check()
        })
      },
      () => undefined // no worker (private window, blocked): the app works online as before
    )
  })
}

function watch(found: ServiceWorkerRegistration) {
  // The first worker on a device has nothing to replace: only a later one waits.
  const waitingNow = () => !!found.waiting && !!navigator.serviceWorker.controller
  if (waitingNow()) set({ waiting: true })
  found.addEventListener("updatefound", () => {
    const next = found.installing
    next?.addEventListener("statechange", () => {
      if (next.state === "installed" && navigator.serviceWorker.controller) set({ waiting: true })
    })
  })
}

/** What stops an update now, if anything: a match open on the deck, or score actions not yet sent. */
export async function updateBlocker(): Promise<UpdateBlocker | null> {
  // Loaded when needed: lib/api uses this file, and the deck uses lib/api.
  const { scoringOnDevice } = await import("@/lib/deck")
  const busy = await scoringOnDevice()
  return busy.scoring > 0 || busy.unsent > 0 ? busy : null
}

/**
 * Switch to the new version if nothing would be lost; otherwise say what is in the way and change
 * nothing. When the API has stopped serving this version, scoring can't go on in it anyway: the update
 * goes ahead and the actions kept in the journal are sent by the new version.
 */
export async function applyUpdate(): Promise<UpdateBlocker | null> {
  if (!state.outdated) {
    const blocker = await updateBlocker()
    if (blocker) return blocker
  }
  const next = registration?.waiting
  if (!next) {
    // No new worker yet (or none at all): the page itself comes from the network on a reload.
    window.location.reload()
    return null
  }
  switching = true
  next.postMessage({ type: "SKIP_WAITING" })
  return null
}

export const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true

/** iPhone and iPad (iPadOS reports itself as a Mac with a touch screen): installed from the Share menu. */
export const isAppleMobile = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.userAgent.includes("Macintosh") && navigator.maxTouchPoints > 1)

/** Show the browser's own install dialog, where it offers one. */
export async function promptInstall(): Promise<boolean> {
  const offered = installPrompt
  if (!offered) return false
  await offered.prompt()
  const { outcome } = await offered.userChoice
  installPrompt = null
  set({ installable: false })
  return outcome === "accepted"
}
