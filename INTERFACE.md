# Cycle Routes — Interface Map

Prototype that downloads open data for a region, scores every street for cycling,
then **automatically generates and rates** routes (A→B alternatives, loop rides,
and a catalogue of suggested rides). Output: a responsive web app (desktop +
phone, installable PWA), printable A4 PDF maps, and GPX for bike computers.

## Data flow

```
OpenStreetMap (Overpass) ─┐ bike network, tags         cycleroutes/data/
  signed cycle routes ────┤ route=bicycle relations    (download + enrich)
  parks/water/viewpoints ─┤                                  │
Copernicus GLO-30 DEM ────┘ elevation                         ▼
                                            data_cache/region_<name>.pkl
                                                              │
scoring/ (LTS, safety, quiet, surface, fun, time) ◄── used by enrich
                                                              │
routing/ router (profiles) · loops · catalog · rating · directions
                                                              │
        ┌──────────────────────┬──────────────────────┬───────┴────────┐
   api/app.py (FastAPI)   export/print_map.py   export/formats.py    cli.py
        │                      (PDF)               (GPX/GeoJSON)
   web/ (Leaflet client)
```

## Modules

### `cycleroutes/config.py`
All defaults: paths, `DEFAULT_REGION`, data-source URLs (`OVERPASS_ENDPOINTS`,
`COPERNICUS_DEM_URL`, `NOMINATIM_URL`), tag lists, speed/scoring constants,
`LTS_COLORS`/`LTS_LABELS`, loop settings, `Profile` dataclass and `PROFILES`
(fastest, safest, family, scenic, flattest, quiet, balanced).

### `cycleroutes/data/` — acquisition & enrichment
| File | Contents |
|---|---|
| `overpass.py` | `with_fallback(download)` tries each Overpass endpoint; `post_query()` |
| `osm_network.py` | `download_bike_network()` (osmnx, simplified MultiDiGraph), `download_scenic_features()` |
| `amenities.py` | `fetch_amenities()` / `load_amenities()`: bike shops, repair, water, toilets, bike share, parking (GeoJSON cache) |
| `cycle_networks.py` | `fetch_cycle_route_ways()` → {way id: rank lcn/rcn/ncn/icn, names} |
| `elevation.py` | `ElevationGrid` (bilinear sample, save/load npz), `fetch_elevation_grid()`, `surface_to_terrain()` (strips buildings/canopy), `climb_along()` |
| `enrich.py` | `enrich()` = `add_geometry`, `add_scenic_fraction`, `add_elevation` (bridges interpolated), `add_cycle_routes`, `add_scores` |
| `region.py` | `Region` dataclass, `build_region()` (download+enrich+pickle), `load_region()` |

### `cycleroutes/scoring/` — per-edge scores (0 bad … 1 good)
| File | Contents |
|---|---|
| `tags.py` | OSM tag normalisation: `values`, `highway`, `speed_limit_kmh`, `lanes`, `cycleway_kind` |
| `lts.py` | `classify(edge)` → Level of Traffic Stress 1–4 (Mekuria/Furth, simplified) |
| `edge_scores.py` | `safety`, `quietness`, `surface`, `fun`, `speed_kmh`, `awkwardness` (parking aisles/driveways), `travel_time_s` |

### `cycleroutes/routing/`
| File | Contents |
|---|---|
| `geo.py` | `haversine_m`, `bearing_deg`, `destination`, `NodeIndex.nearest` (ported from pyNav) |
| `route.py` | `Route` (edges, coords, elevation_profile, length/time), `edges_from_nodes`, `overlap` |
| `router.py` | `make_cost(profile, penalties)`, `custom_profile`, `Router.route/alternatives/snap`, `RoutingError` |
| `loops.py` | `generate_loops(router, start, km, profile, count)` — triangle waypoints + reuse penalty |
| `rating.py` | `rate(route, fastest_time_s)` → stats + 0–10 ratings (safety, fun, traffic, hills, speed, surface, overall) |
| `directions.py` | `cue_sheet(route)` → `Cue` list (turns, street names, LTS) |
| `catalog.py` | `build_catalog()` suggested loops from centre + big parks; `load_catalog()` |

### `cycleroutes/tracking/` — GPS (ported from gps-tracker + pyNav, Qt-free)
| File | Contents |
|---|---|
| `nmea.py` | `Fix` dataclass, `NmeaParser` (RMC+GGA, checksums, $GN/$GL talkers), `estimate_accuracy_m`, `to_nmea_rmc` |
| `providers.py` | `SerialGPSProvider` (thread), `IPLocationProvider` (opt-in), `ManualProvider`, `PushProvider`, `discover_serial_gps`, `ProviderManager` |
| `store.py` | `RideStore` (SQLite rides + points), `drop_spikes`, `track_stats`, `ride_gpx`, `ride_csv` |
| `navigator.py` | `Navigator.update(fix)` → `Progress` (along/remaining, next cue, off-route debounce, arrival) |
| `matching.py` | `match_track(router, points)` → matched `Route` + coverage (to rate a ridden track) |

### `cycleroutes/devtools/` — automated UI testing with screenshots
| File | Contents |
|---|---|
| `session.py` | `ShotSession` (numbered screenshots + checks + auto-captured JS/HTTP errors), `Shot`, `write_manifest` |
| `scenarios.py` | Desktop/phone/dark walkthroughs, exports (GPX parse, PDF render via pymupdf), `Points`, `frame` |
| `scenarios_ride.py` | Amenities layer; simulated GPS ride (navigate, off-route, reroute, arrive, save, My rides) |
| `report.py` | `write_report()` → `report.html` contact sheet |
| `screenshots.py` | `run()` (starts a temporary server, isolated test ride DB), `print_summary()` |

### `cycleroutes/services/`
- `geocoding.py` — `NominatimGeocoder.search(q, viewbox)` (Qt-free port of pyNav's `NominatimProvider`)

### `cycleroutes/export/`
- `formats.py` — `to_gpx` (track + cue waypoints + elevation), `route_segments_geojson`, `network_geojson`
- `tiles.py` — `TileManager` (SQLite tile cache, Qt-free port of gps-tracker's), `stitch`, `choose_zoom`
- `print_map.py` — `route_pdf(route, stats, title, basemap)` A4: map page + ratings/elevation/cue pages

### `cycleroutes/api/`
- `state.py` — `AppState` (region, router, stored routes, navigators, `RideStore`, `ProviderManager`), `state()`, `set_state()`, `latlon()`
- `app.py` — FastAPI: `/api/region`, `/api/network`, `/api/amenities`, `/api/alternatives`, `/api/route`,
  `/api/loop`, `/api/suggested`, `/api/geocode`, `/api/export/{id}.gpx|.pdf`; serves `web/`
- `tracking_api.py` — `/api/gps/sources|scan|live`, `/api/rides` (start, points, finish, list, get, .gpx, .csv, delete),
  `/api/navigate/{route_id}`, and `POST /location` (pyNav/Pythonista iPhone tracker format); `fix_from_dict()`
- `serialize.py` — `route_payload()` (geojson segments, cues, downsampled elevation)

### `cycleroutes/cli.py`
`cycleroutes build | route | loop | catalog | amenities | gps | screenshots | serve [--https --serial-gps --ip-location]`.

### `web/` (static client, no build step)
- `index.html`, `style.css` (desktop side panel → phone bottom sheet, dark mode), `manifest.json`, `icon.svg`
- `js/map.js` — `RouteMap` (Leaflet, CyclOSM/OSM layers, stress layer, route drawing, pins)
- `js/cards.js` — `renderCards`, `elevationSvg` (ratings, stress mix, cues, export links)
- `js/main.js` — tabs, search, map clicks, API calls, rides tab wiring
- `js/ride.js` — `RideController` (device GPS or server GPS feed, recording, navigation banner, reroute, wake lock)
- `js/rides.js` — `renderRides`, `summaryHtml` (My rides list)

### `tests/` (offline, synthetic 6×6 street grid in `conftest.py`)
`test_scoring.py`, `test_routing.py`, `test_api.py`, `test_tracking.py` (NMEA, navigator, store, serial via pty).

### `hardware/gps_i2c_serial/`
Arduino sketch (from gps-tracker) that reads an Adafruit I2C GPS and emits NMEA over USB at 115200 baud —
the input `SerialGPSProvider` expects.

### `scripts/`
- `build_demo.py` — build the default region with verbose logging.

## Reuse from sibling projects
- pyNav `NominatimProvider` → `services/geocoding.py`; distance/bearing maths → `routing/geo.py`;
  GPX/GeoJSON export → `export/formats.py` (extended with elevation + cues).
- gps-tracker `TileManager`/`TILE_SERVERS` (incl. CyclOSM) → `export/tiles.py`.
- gps-tracker `SerialGPSProvider`/`IPLocationProvider`/device discovery + pyNav `GPSProvider` accuracy
  heuristic → `tracking/nmea.py`, `tracking/providers.py`; gps-tracker CSV logging → `tracking/store.py`.
- pyNav `RoutingEngine.update_location` → `tracking/navigator.py` (projection onto the route, off-route).
- pyNav `iphoneTracking/macbook_server.py` → `POST /location` in `api/tracking_api.py` (same JSON).
- pyNav `search_nearby_pois` → `data/amenities.py`.
- Not reused: PyQt widgets/threads (web client instead); pyNav's OSRM/GraphHopper clients (can't take our
  scores); pyNav offline MBTiles/vector tile rendering (future: PWA offline tiles); the iPhone sensor
  test apps (motion sensors aren't needed for cycling routes).
