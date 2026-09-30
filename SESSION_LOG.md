# Session Log

## 2026-09-29 — Prototype v0.1

**Goal:** automatically generate and rate cycling routes (safety, fun, hills, speed,
traffic, surface) from open data; usable on desktop and phone, and printable.

**Reviewed sibling projects**
- `gps-tracker`: PyQt tracker. Reused `TileManager` + tile servers (CyclOSM) → `export/tiles.py`.
- `pyNav`: PyQt navigator. Reused Nominatim geocoder, distance/bearing maths and GPX/GeoJSON export.
  Its OSRM/GraphHopper clients were not reused because their public bike profiles can't take our scores.

**Built**
- Data layer: OSM bike network (osmnx), signed cycle-route relations, scenic features,
  Copernicus DEM; Overpass fallback across public mirrors (overpass-api.de refused connections).
- Scoring: LTS 1–4, safety, quietness, surface, fun, hill-aware travel time, signal delays.
- Routing: 7 profiles + custom sliders, alternatives with de-duplication, loop generator,
  suggested-ride catalogue, 0–10 ratings, cue sheet.
- Outputs: FastAPI + Leaflet web app (responsive, PWA manifest), A4 PDF, GPX.
- Tests: 18 offline tests on a synthetic grid (all passing).

**Verified on real data (Austin, 4 km radius: 13.6k nodes / 34k edges, build ~3 min)**
- UT campus → Zilker: 7 distinct rated options; e.g. fastest 6.0 km (safety 5.3) vs family
  13.7 km (safety 9.7, 76% signed routes). Loops land within ~5% of target distance.
- Catalogue: 45 suggested loops from centre + 4 reachable parks in ~10 s.
- Headless Chrome check (scripts/ui_check.py): desktop + phone flows, no console errors.
- Fixes found by the real run: DSM building noise (added morphological opening; climb
  116 m → 75 m), parking-aisle zig-zags (awkwardness penalty), park hubs off-network.

**Known issues**
- "Family" can detour heavily (2.3× here) because downtown is almost all LTS 3+; consider a
  maximum-detour cap or showing "no low-stress option" instead.
- overpass-api.de refused connections from this machine; the build uses mirrors.

**Next ideas**
- Crash data (e.g. Austin open data / NHTSA FARS, UK STATS19) as a safety layer.
- Traffic counts where cities publish them; intersection-crossing stress.
- Move to GraphHopper custom model or BRouter profile for larger regions.
- Offline tiles and service worker for the PWA; user hazard reports.

## 2026-09-29 — Region too small for real use
- User's A→B points (Hyde Park / North Loop, lat ~30.31–30.32) were outside the 4 km demo box
  (north edge 30.298), so every request failed with "N m from the nearest rideable street".
- Default region is now centre (30.29, -97.74), 6 km radius: 25.9k nodes / 66k edges, build ~23 min
  (mostly the Overpass mirror download). A→B routing is still < 0.4 s. The old region is kept as
  data_cache/region_austin_small.pkl.
- UI: the area outside the region is shaded, the map opens fitted to the region, and points outside it
  (click, drag, geolocation, search) are rejected straight away with a clear message.

## 2026-09-29 — Screenshot testing tool + GPS features from gps-tracker / pyNav
- New `cycleroutes screenshots`: headless Chrome walkthrough (desktop, phone, dark mode, simulated GPS
  ride), 28 screenshots + PDF renders, 66 automatic checks, `report.html` contact sheet.
- Bugs found by reviewing the screenshots and fixed:
  - Phone bottom sheet: results squeezed into a tiny scroller; collapsed sheet lost its handle (could not
    reopen). Now the whole sheet scrolls with a sticky handle/tabs.
  - Cue sheet: runs of "Turn left onto service road" every few metres → merged.
  - Amenities: ~400 bike-parking pins buried downtown → zoom-dependent layers.
  - "Show on map" in My rides replaced the rides list; `/api/rides/{id}.gpx` shadowed by `/{id}` (422).
  - Ride distance showed 0 km for fast/replayed tracks (80 km/h cut-off) → proper spike filter.
  - Nav banner showed a stale turn while off-route; "then …" preview lower-cased street names.
- Imported (Qt-free): NMEA parsing + serial GPS + device discovery + IP/manual sources; ride recording
  (SQLite, GPX/CSV); live navigation with off-route/reroute; iPhone tracker `POST /location` endpoint;
  cyclist amenities (698 in Austin); Arduino GPS sketch; `serve --https` for phone GPS over Wi-Fi.
- Tests: 27 passing (NMEA, navigator, store, spike filter, serial GPS via pty, ride/iPhone API flow).
- Not verified: a real USB GPS receiver and a real phone outdoors (simulated only).
