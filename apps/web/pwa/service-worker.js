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

/** Paths that are never answered from a cache: the API, uploaded files, the admin. */
const LIVE = ["/api/", "/media/", "/admin/", "/static/", "/health/"]

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
