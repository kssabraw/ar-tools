// AR Tools PWA service worker — installability only (PRD §13: offline is NOT
// required in v1). Network-first for everything; no caching, so deploys are
// never masked by a stale cache.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', () => {
  // Intentionally empty: the browser handles all requests normally. A fetch
  // handler must exist for some installability heuristics.
})
