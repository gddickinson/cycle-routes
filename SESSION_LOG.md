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

## 2026-09-30 — "Implement all ideas, use all open data"
**Data added (Austin):** USGS 3DEP bare earth (5 m), 772 bike crashes (Vision Zero), city bike-comfort
on 10.3k segments, TxDOT traffic counts on 7.8k segments (freeway→frontage mis-snaps rejected),
Meta/WRI canopy shade, US DOT noise, 29 bike counters, live WZDx work zones (≈380 closed segments),
3.4k Overture places, CapMetro GBFS, Open-Meteo weather, sunrise/sunset.
**Features:** bike types, departure time/darkness, wind/heat, closures, via points, crossing
penalties, family detour cap, Shadiest profile, stops along route, water gaps, stages, compare,
hazard reports, street feedback, places, favourites, learned profile, share links, live location
share, voice guidance, ride heatmap/coverage, open-data layers, network score, region build/switch,
strip maps, A6 cue card, QR codes, fixed-scale printing, offline service worker, Dockerfile.
**Bugs found & fixed on the way:** mph thresholds (25 mph residential was LTS 2–3), source report
overwritten by `--only` runs, AADT on frontage roads, crossing flags along bike lanes, settings
panel overflow, café marker clutter, closure colour clashing with LTS 4 red, PROJ from another
conda env breaking rasterio.
**Not done:** Garmin/Wahoo sync, Mapillary, OpenRouteService, TxDOT keyed feed, Strava (keys/terms),
native background-GPS wrapper, bike+transit routing, BikeMaps (no Austin data), larger-area routing
engine (GraphHopper). Docker image written but not built (daemon not running).
**Tests:** 44 unit/API tests; screenshot suite 40 screenshots / 86 checks, all passing.

## 2026-09-30 — Road-type exclusions, bike-lanes-only, cycle trails
- Avoid options (major, secondary, busy by AADT, LTS 3-4, unpaved, steps, sidewalks, service,
  trails) as a 40x soft penalty; "bike lanes, cycle paths & trails only" as a 5x penalty on
  streets without bike space. Routes report any unavoidable avoided km.
- Trails: osmnx bike filter + footways/paths/bridleways allowing bikes (not sidewalks) + any
  mtb:scale way. Austin rebuild: +195 segments, 76 km of trails (29 km unpaved); Barton Creek
  Greenbelt now reachable. New profiles Trails & greenways, Mountain-bike trails; trails layer.
- Findings: OSM has almost no mtb:scale in central Austin (1 way, grade 0), so the MTB style uses
  unpaved/rough trail surfaces. "Avoid major roads" originally cancelled bike-lanes-only (Austin's
  protected lanes are on major roads) -> protected lanes exempted. Fixed a race where a slow
  planning response drew routes after switching tab; SQLite reads now locked (intermittent 500).
- Tests 53 passing; screenshot suite 45 screenshots / 93 checks passing.

## 2026-09-30 — Bigger area, data-source options, reuse of downloads, offline map, walking
- Area: 10 km radius around (30.28, -97.74). Overpass stalled (>25 min), so street data now comes
  from the BBBike Austin extract (.osm.pbf, weekly) read locally with osmium using the same filters:
  whole network in ~75 s. 138k cycling segments; 285k walking segments.
- Data-source options: per area (streets extract/Overpass/auto, elevation 3DEP/Copernicus, each layer
  on/off, reuse downloads) in More › Data sources with apply/rebuild jobs; per route "all data" vs
  "OpenStreetMap only" scoring (precomputed OSM-only variants) and rider-reports switch.
- Reuse: download cache keyed by covered area (clip on reuse, max ages per source); new areas inside
  a built one are cut from it (5 s, scores kept); cycling and walking share downloads.
- Offline: vector basemap from the Protomaps daily build into SQLite, served at /tiles; "save map &
  data on this device" precaches it; data export/import; Leaflet + plugin bundled. Verified by
  cutting the network in the screenshot run.
- Walking: separate network (sidewalks, footways, steps…), pedestrian stress, pedestrian crashes
  (1,569), city sidewalk inventory (46k with / 16k without), street life & sights, Tobler speed,
  step-free; trip types commute/urban/sightseeing/hike/green/shady/step-free/safest; sightseeing
  tours; suggested walks; walk navigation & recording.
- Fixes along the way: stale per-name caches on rebuild, osmnx bbox order in extract reader,
  inherited "downloaded now" labels, offline precache URL list, service-worker offline answers,
  scenic matching 25 min → ~2 min (spatial index, identical results). A* tried and reverted
  (identical routes, no speed-up).
- Tests: 69 unit/API; screenshot suite 50 screenshots / 107 checks, all passing.
