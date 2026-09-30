# Cycle Routes — Interface Map

Downloads open data for a region, scores every street for cycling, then **automatically
generates and rates** routes (A→B alternatives, loops, suggested rides) for the rider's
context (bike type, time, weather, closures). Outputs: responsive web app / offline-capable
PWA, printable PDFs (overview, strip maps, cue card), GPX; plus GPS riding & recording.

## Data flow

```
OpenStreetMap (Overpass): streets, tags, signed routes, parks ─┐
Copernicus DEM, or USGS 3DEP bare earth (US) ───────────────────┤   data/  (+ data/sources/)
City of Austin: crashes, bike-comfort, counters ────────────────┤   download, join to edges,
TxDOT traffic counts · Meta/WRI canopy · US DOT noise ──────────┤   cache in data_cache/
Overture places · OSM amenities ────────────────────────────────┘          │
                                                                region_<name>.pkl
scoring/ (LTS from tags + measured traffic + city comfort; safety incl. crashes;       │
          quietness incl. traffic/noise; fun incl. shade; crossings) ◄─ enrich/apply   │
live (api/live.py): work zones (WZDx) · Open-Meteo weather · sun · hazard reports ─► RouteContext
routing/ router (profiles, via, context, family cap) · loops · catalog · rating · stops · stages
        │                         │                         │
   api/ (FastAPI) ───────── export/ (PDF/GPX) ──────── tracking/ (GPS, rides, navigation)
        │
   web/ (Leaflet client, service worker)
```

## Python modules

### `cycleroutes/config.py`
All defaults: paths, `DEFAULT_REGION`, data-source URLs (Overpass, Copernicus, 3DEP, Austin
Socrata ids, TxDOT, canopy, noise, Overture, GBFS, Open-Meteo), LTS colours, GPS settings,
`Profile` (+ shade, crossings weights, `prefer`) and `PROFILES` (fastest, safest, family, scenic,
flattest, quiet, trails, mtb, shady, balanced), `TRAIL_FILTERS` (extra OSM ways: bike-legal trails),
`AVOID_PENALTY`, `INFRA_ONLY_PENALTY`, `PREFER_PENALTY`, `CROSSING_COST_M`, `FAMILY_MAX_DETOUR`, `HOT_APPARENT_C`.
`cycleroutes/__init__.py` pins GDAL/PROJ data to rasterio's bundled copy.

### `cycleroutes/data/`
| File | Contents |
|---|---|
| `overpass.py` | `with_fallback(download)` across Overpass mirrors; `post_query()` |
| `osm_network.py` | `bike_filters()` (osmnx bike + trails), `download_bike_network()`, `download_scenic_features()` |
| `cycle_networks.py` | `fetch_cycle_route_ways()` (lcn/rcn/ncn/icn relations) |
| `elevation.py` | `ElevationGrid`, `fetch_elevation_grid()` (Copernicus), `surface_to_terrain()`, `climb_along()` |
| `amenities.py` | `fetch_amenities()` / `load_amenities()` (water, toilets, bike shops, parking, bike share) |
| `enrich.py` | `enrich()`: geometry, scenic, elevation, cycle routes, `add_scores()` (bearing, LTS, scores), `add_crossings()` |
| `region.py` | `Region` (+ `sources` report), `build_region()` (reuse a covering built area → extract → Overpass), `find_covering_region`, `save_region` (+ `regions.json` index), `load_region` |
| `extract.py` | build from an OSM extract (.osm.pbf via osmium): `parse_filter` (same Overpass filters), `extract_for`, `fetch_extract`, `build_from_extract` |
| `cache.py` | reuse downloads: `json_source` / `array_source` answer from any fresher cached download covering the area (clipped), `summary()`, `MAX_AGE_S` |
| `settings.py` | per-area data-source choices (`network`, `elevation`, `prefer_cached`, `layers`) in `settings_<area>.json` |

### `cycleroutes/data/sources/` — extra open data (each keyless, applied where it has coverage)
| File | Contents |
|---|---|
| `usgs_3dep.py` | `fetch_3dep_grid()` bare-earth DEM (chunked, parallel, retries), `covers()` |
| `austin.py` | `fetch_bike_crashes`, `fetch_bike_facilities` (+`COMFORT_TO_LTS`), `fetch_counters`, `fetch_work_zones`, cache helpers |
| `txdot_aadt.py` | `fetch_stations()` measured traffic (annual + 5-year counts) |
| `canopy.py` | `fetch_canopy()` → `CanopyGrid.heights()` (Meta/WRI 1 m canopy tiles) |
| `noise.py` | `fetch_noise()` decodes US DOT noise tiles → `NoiseGrid.sample()` dB |
| `overture.py` | `fetch_places()` via DuckDB on S3 GeoParquet; `STOP_CATEGORIES`; `load()` |
| `join.py` | `edges_frame`, `overlap_join`, `nearest_edges`, `propagate_by_name`, `sample_points`, `set_both_directions` |
| `apply.py` | `apply_all(region, refresh, only)` honouring settings (layer on/off, elevation choice) via the cache; `AADT_CAP_BY_CLASS` |

### Walking (mode "walk")
- `data/walk_region.py` — `build_walk_region(area)` → region `<area>--walk` (walk filters, both
  directions; elevation/shade/noise/traffic via the cache; pedestrian crashes, city sidewalks,
  lively/sights from Overture); `walk_name()`, `walk_filters()`.
- `scoring/walk_scores.py` — `pedestrian_stress`, `has_sidewalk`, `safety`, `fun`, `surface`,
  `speed_kmh` (Tobler), `accessible`, `score_edge` (writes the router's attribute names).
- `routing/tours.py` — `pick_sights`, `order_stops` (nearest neighbour + 2-opt), `generate_tour`.
- `config.WALK_PROFILES`, `config.MODES`; `context.WALK_AVOID` / `BIKE_AVOID`; graphs carry
  `graph.graph["mode"]` and `["base_kmh"]`; API endpoints take `mode=bike|walk`; `/api/tour`.

### `cycleroutes/scoring/`
- `tags.py` — tag helpers incl. `is_trail`, `mtb_scale`, `has_bike_infra`.
- `lts.py` — `classify()` (OSM, mph-aware thresholds), `with_measured_traffic()`, `effective()` (+ city comfort).
- enrich also stores OpenStreetMap-only variants (`lts_osm`, `safety_osm`, `quiet_osm`, `fun_osm`) for `data=osm` routing.
- `edge_scores.py` — `safety` (crashes), `quietness` (AADT, noise), `surface`, `fun` (shade), `speed_kmh`, `awkwardness`, `travel_time_s`.

### `cycleroutes/routing/`
| File | Contents |
|---|---|
| `geo.py` | haversine, bearing, destination, `NodeIndex` |
| `route.py` | `Route` (edges, `ctx`, coords, profile, time), `edges_from_nodes`, `overlap` |
| `context.py` | `RouteContext` (bike, dark, wind, heat, closures, reports, `avoid`, `infra_only`, `prefer`), `BIKE_TYPES`, `AVOID_TYPES` (protected lanes exempt), `edge_multiplier`, `travel_time_s`, `headwind_kmh` |
| `router.py` | `make_cost(profile, penalties, graph, ctx)` (+ crossing penalty), `Router.route(via, ctx)`, `family_route`, `alternatives` |
| `loops.py` | `generate_loops(..., ctx)` |
| `rating.py` | `rate()` — ratings incl. shade; trail %, MTB grade, avoided km, crashes, crossings, busiest AADT, noise |
| `directions.py` | `cue_sheet()` with service-road jog merging |
| `catalog.py` | suggested rides from centre + reachable parks |
| `stops.py` | `along(route, features)`, `longest_dry_stretch()` |
| `stages.py` | `split_stages(route, km_per_day, stays)` |
| `network_score.py` | `low_stress_score()` (BNA-style connectivity) |

### `cycleroutes/tracking/` — GPS (from gps-tracker/pyNav)
`nmea.py` (Fix, NmeaParser), `providers.py` (serial/IP/manual/push, `ProviderManager`), `store.py`
(`RideStore`, `drop_spikes`, `track_stats`, GPX/CSV), `navigator.py` (`Navigator.update`), `matching.py` (`match_track`).

### `cycleroutes/community/store.py`
`CommunityStore`: hazards (`HAZARD_TYPES`, expiry, confirm/resolve), street feedback, places,
favourites, learned weights (`record_choice`, `learned_weights`), live-share tokens.

### `cycleroutes/offline/`
- `basemap.py` — `download_basemap()` extracts the area's vector tiles from the Protomaps daily
  OSM build (HTTP ranges) into `data_cache/basemap_<area>.sqlite`; `LocalBasemap` reads them.
- `backup.py` — `export_json()` / `import_json()` of rides, points, hazards, places, favourites, feedback.

### `cycleroutes/services/`
`geocoding.py` (Nominatim), `weather.py` (Open-Meteo `forecast/at/along_ride/advice`), `sun.py`
(`sun_times`, `daylight_left`), `bikeshare.py` (GBFS `stations()`).

### `cycleroutes/export/`
`formats.py` (GPX/GeoJSON), `tiles.py` (TileManager), `print_map.py` (`route_pdf(layout, scale, qr_url)`,
map/details pages, QR), `print_layouts.py` (`strip_pages`, `cue_card_pages`).

### `cycleroutes/api/`
| File | Contents |
|---|---|
| `state.py` | `AppState` (region, router, routes, navigators, rides, community, live, gps) |
| `live.py` | `LiveData`: work zones → closed/restricted edges, report multipliers, `context()` |
| `app.py` | region, network, alternatives/route/loop (via, bike, depart, weather, closures, avoid, infra_only, learned), suggested, amenities, geocode, exports, `/sw.js` |
| `planning_api.py` | conditions, weather/{rid}, stops/{rid}, stages/{rid}, layers/{name} (incl. trails), network/score, regions |
| `community_api.py` | hazards, feedback, places, favourites, learned profile, ride share + `/share/{token}` page |
| `sources_api.py` | `GET/POST /api/sources` (choices, availability, downloads, apply/rebuild job) |
| `offline_api.py` | `/tiles/{z}/{x}/{y}.mvt`, offline status/manifest, basemap download job, `/api/backup` export/import |
| `tracking_api.py` | GPS sources/live, `/location` (iPhone tracker), rides (+ heatmap), navigate |
| `serialize.py` | `route_payload()` |

### `cycleroutes/devtools/` — `cycleroutes screenshots`
`session.py` (ShotSession), `scenarios.py`, `scenarios_plan.py`, `scenarios_ride.py`, `scenarios_walk.py`, `scenarios_offline.py`, `report.py`, `screenshots.py`.

### `cycleroutes/cli.py`
`build | walk | sources | offline | catalog | amenities | route | loop | gps | screenshots | serve [--https --serial-gps --ip-location]`.

## Web client (`web/`, no build step)
| File | Contents |
|---|---|
| `index.html`, `style.css`, `manifest.json`, `icon.svg`, `share.html`, `sw.js` | page, styles, PWA, live-share viewer, service worker (offline map + data precache) |
| `vendor/` | Leaflet 1.9.4 and protomaps-leaflet 5 (bundled so the app works offline; BSD licences included) |
| `js/main.js` | app wiring: tabs, points, planning requests, results, rides |
| `js/util.js` | `$`, `api/post/del`, `esc`, `remember/recall`, `copyText` |
| `js/settings.js` | `Settings` (bike, depart, weather, closures, conditions), `planLink`, `readLink` |
| `js/map.js` | `RouteMap`: layers, pins, via pins, stops, position, tracks, amenities |
| `js/layers.js` | `Layers`: open-data layers + press-and-hold menu (hazard, feedback, places) |
| `js/plan.js` | `Plan`: via points, places, favourites, stops/weather details, stages, compare |
| `js/cards.js` | `renderCards` (ratings, open-data facts, print menu, save/link) |
| `js/ride.js` | `RideController`: GPS feed, navigation banner, voice, reroute, live share |
| `js/rides.js`, `js/search.js`, `js/more.js`, `js/sources.js` | rides list, place search, More tab (score, regions, offline), data-sources panel |

## Tests (`tests/`, offline)
`test_scoring`, `test_routing`, `test_api`, `test_tracking`, `test_sources`, `test_planning`, `test_road_options`, `test_offline`, `test_data_sources`, `test_walking`
(synthetic 6×6 grid in `conftest.py`; weather stubbed).

## Other
`hardware/gps_i2c_serial/` Arduino NMEA sketch · `Dockerfile` · `scripts/build_demo.py`.
