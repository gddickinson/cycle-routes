// Offline support: map tiles cache-first (capped) as you browse; the app and API are
// network-first with the cache as fallback, so a planned route stays available offline.
const SHELL = "cr-shell-v2", TILES = "cr-tiles-v1", API = "cr-api-v1";
const SHELL_FILES = ["/", "/static/style.css", "/static/js/main.js", "/static/js/map.js", "/static/js/cards.js",
  "/static/js/ride.js", "/static/js/rides.js", "/static/js/settings.js", "/static/js/layers.js",
  "/static/js/plan.js", "/static/js/more.js", "/static/js/util.js", "/static/js/search.js", "/static/manifest.json", "/static/icon.svg"];
const MAX_TILES = 3000;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => ![SHELL, TILES, API].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

async function trimTiles() {
  const cache = await caches.open(TILES);
  const keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(k);
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (/tile|cyclosm/.test(url.hostname)) {           // map tiles: cache first
    e.respondWith(caches.open(TILES).then(async (cache) => {
      const hit = await cache.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok || res.type === "opaque") { cache.put(e.request, res.clone()); trimTiles(); }
      return res;
    }));
  } else if (url.origin === location.origin && url.pathname.startsWith("/api/")) {   // API: network first
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok && !url.pathname.includes("/export/")) caches.open(API).then((c) => c.put(e.request, res.clone()));
      return res;
    }).catch(() => caches.match(e.request)));
  } else if (url.origin === location.origin) {        // app shell: network first, cache offline
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) caches.open(SHELL).then((c) => c.put(e.request, res.clone()));
      return res;
    }).catch(() => caches.match(e.request)));
  }
});
