/* Pass-through service worker: exists so the app is installable as a
   PWA. Deliberately does NOT cache anything — data must never be stale. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));
self.addEventListener("fetch", (e) => e.respondWith(fetch(e.request)));
