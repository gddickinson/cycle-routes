// Offline support: map tiles cache-first (capped) as you browse; the app and API are
// network-first with the cache as fallback, so a planned route stays available offline.
const SHELL = "cr-shell-v5", TILES = "cr-tiles-v1", API = "cr-api-v1", LOCAL_TILES = "cr-offline-map-v1";
const SHELL_FILES = ["/", "/static/style.css", "/static/js/main.js", "/static/js/map.js", "/static/js/cards.js",
  "/static/js/ride.js", "/static/js/rides.js", "/static/js/settings.js", "/static/js/layers.js",
  "/static/js/plan.js", "/static/js/more.js", "/static/js/util.js", "/static/js/search.js", "/static/js/sources.js", "/static/js/voice.js", "/static/js/trip.js", "/static/js/notice.js", "/static/manifest.json", "/static/icon.svg",
  "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css", "/static/vendor/protomaps-leaflet.js",
  "/static/vendor/leaflet/images/layers.png", "/static/vendor/leaflet/images/layers-2x.png"];
const MAX_TILES = 3000;

// When offline and nothing was saved for a request, answer clearly instead of failing.
const offlineJson = () => new Response(JSON.stringify({ detail: "You're offline and this wasn't saved on this device." }),
  { status: 503, headers: { "Content-Type": "application/json" } });
const offlineEmpty = () => new Response(null, { status: 204 });
const orOffline = (fallback) => (hit) => hit || fallback();

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => ![SHELL, TILES, API, LOCAL_TILES].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

async function trimTiles() {
  const cache = await caches.open(TILES);
  const keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(k);
}

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.origin === location.origin && url.pathname.startsWith("/tiles/")) {   // stored offline map
    e.respondWith(caches.match(e.request, { cacheName: LOCAL_TILES })
      .then((hit) => hit || fetch(e.request).catch(offlineEmpty)));
    return;
  }
  if (/tile|cyclosm/.test(url.hostname)) {           // map tiles: cache first
    e.respondWith(caches.open(TILES).then(async (cache) => {
      const hit = await cache.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request).catch(offlineEmpty);
      if (res.status === 204) return res;
      if (res.ok || res.type === "opaque") { cache.put(e.request, res.clone()); trimTiles(); }
      return res;
    }));
  } else if (url.origin === location.origin && url.pathname.startsWith("/api/")) {   // API: network first
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok && !url.pathname.includes("/export/")) caches.open(API).then((c) => c.put(e.request, res.clone()));
      return res;
    }).catch(() => caches.match(e.request).then(orOffline(offlineJson))));
  } else if (url.origin === location.origin) {        // app shell: network first, cache offline
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) caches.open(SHELL).then((c) => c.put(e.request, res.clone()));
      return res;
    }).catch(() => caches.match(e.request).then(orOffline(offlineEmpty))));
  }
});

// "Save map & data on this device": fetch and store every URL, reporting progress.
self.addEventListener("message", (e) => {
  if (e.data?.type !== "precache") return;
  const urls = e.data.urls;
  const client = e.source;
  e.waitUntil((async () => {
    const tiles = await caches.open(LOCAL_TILES), api = await caches.open(API), shell = await caches.open(SHELL);
    await shell.addAll(SHELL_FILES).catch(() => {});
    let done = 0, failed = 0;
    for (let i = 0; i < urls.length; i += 20) {
      await Promise.all(urls.slice(i, i + 20).map(async (u) => {
        try {
          const res = await fetch(u);
          if (res.ok || res.status === 204) await (u.startsWith("/tiles/") ? tiles : api).put(u, res);
          else failed++;
        } catch { failed++; }
        done++;
      }));
      client?.postMessage({ type: "precache-progress", done, total: urls.length, failed });
    }
  })());
});
