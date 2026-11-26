// Coast TT service worker (REQ-035). The build fills in BUILD and SHELL (see pwa-worker.ts): one version
// per release, so each release keeps its own copy of the app shell and old copies go once it takes over.
//
// What it keeps: the app's own files (the page, scripts, styles, fonts, icons). What it never keeps:
// anything from the API, signed attachment links or other sites. Private data stays with the server or
// in the score journal (IndexedDB), never in a generic cache.
//
// A new version waits: it takes over only when the page asks (SKIP_WAITING), and the page asks only once
// no match is being scored and no score action is waiting to be sent.

const BUILD = "__BUILD__"
const SHELL = /* __SHELL__ */ []
const CACHE = `coast-tt-shell-${BUILD}`
const PREFIX = "coast-tt-shell-"
const PAGE = "/index.html"

/** Paths that are never answered from a cache: the API, uploaded files, the API's own static files. /admin is
 * the app's own back office, so it is served from the kept shell like any other page. */
const LIVE = ["/api/", "/media/", "/static/", "/health/"]

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)))
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name.startsWith(PREFIX) && name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting()
  if (event.data?.type === "BUILD") event.source?.postMessage({ type: "BUILD", build: BUILD })
})

self.addEventListener("fetch", (event) => {
  const request = event.request
  if (request.method !== "GET") return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (LIVE.some((prefix) => url.pathname.startsWith(prefix))) return

  // Pages: the network first so a deep link gets the current page, and this release's shell offline.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.open(CACHE).then((cache) => cache.match(PAGE)).then((page) => page ?? Response.error())))
    return
  }

  // Fingerprinted files never change: the copy kept is good. A chunk loaded later is kept on first use.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(fromCacheThenNetwork(request))
    return
  }

  // Unversioned public files (icons, manifest, place lists): kept copy at once, refreshed behind it.
  if (SHELL.includes(url.pathname) || url.pathname.startsWith("/geography/")) {
    event.respondWith(fromCacheRefreshing(request, event))
  }
})

// Push messages (REQ-019, TASK-034): a copy of an inbox alert. The tag is the alert's subject, so a newer
// alert about the same match or activity replaces the older one on the lock screen. Opening it goes to
// the alert's link, which shows the subject as it is now.
self.addEventListener("push", (event) => {
  let alert = {}
  try {
    alert = event.data ? event.data.json() : {}
  } catch {
    alert = { title: event.data?.text() }
  }
  const title = alert.title || "Coast TT"
  event.waitUntil(
    self.registration.showNotification(title, {
      body: alert.body || "",
      tag: alert.tag || alert.id,
      renotify: Boolean(alert.tag),
      requireInteraction: Boolean(alert.urgent),
      icon: "/icons/icon-192.png",
      badge: "/favicon-32.png",
      data: { link: safeLink(alert.link) },
    })
  )
})

self.addEventListener("notificationclick", (event) => {
  event.notification.close()
  const link = safeLink(event.notification.data?.link)
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((open) => {
      const tab = open.find((client) => new URL(client.url).origin === self.location.origin)
      if (tab) return tab.focus().then((focused) => (focused ?? tab).navigate(link).catch(() => undefined))
      return self.clients.openWindow(link)
    })
  )
})

/** Only paths in this app: a message never opens another site. */
function safeLink(link) {
  return typeof link === "string" && link.startsWith("/") && !link.startsWith("//") ? link : "/notifications"
}

async function fromCacheThenNetwork(request) {
  const cache = await caches.open(CACHE)
  const kept = await cache.match(request)
  if (kept) return kept
  const response = await fetch(request)
  if (response.ok && response.type === "basic") await cache.put(request, response.clone())
  return response
}

async function fromCacheRefreshing(request, event) {
  const cache = await caches.open(CACHE)
  const kept = await cache.match(request)
  const fresh = fetch(request).then(async (response) => {
    if (response.ok && response.type === "basic") await cache.put(request, response.clone())
    return response
  })
  if (kept) {
    event.waitUntil(fresh.catch(() => undefined))
    return kept
  }
  return fresh
}
