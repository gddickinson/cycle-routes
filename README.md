# Cycle Routes (prototype)

Automatically generated, rated bike routes from open data. Every street is scored
for **safety** (Level of Traffic Stress), **traffic**, **fun/scenery**, **hills**,
**surface** and **speed**, and every route gets a 0–10 rating on each.

- **A → B**: one route per riding style (fastest, safest, family, scenic, flattest,
  quietest, balanced), near-duplicates merged, all rated side by side, plus a
  "custom mix" with sliders.
- **Loop rides**: pick a start and distance; loops are generated in several
  directions and ranked.
- **Suggested rides**: a pre-built catalogue of loops from the centre and the
  largest parks.
- **Outputs**: web app (desktop and phone, can be installed as an app), printable
  A4 PDF (map, legend, scale, km markers, ratings, elevation profile, cue sheet),
  GPX with elevation and turn cues for Garmin/Wahoo.

## Walking
Switch **🚲 Bike / 🚶 Walk** at the top. Walking uses its own network (sidewalks, footways,
steps, pedestrian streets, shared paths) scored for people on foot: pedestrian stress
(sidewalks, traffic, speed), pedestrian crash records, the city's sidewalk inventory and
condition ratings, shade, noise, street life (cafés/shops) and nearby sights; walking time
follows Tobler's hiking function. Trip types: **Commute, Urban adventure, Sightseeing, Hike,
Green & quiet, Shady stroll, Step-free** (wheelchair/stroller: no steps, gentle slopes,
smooth) and **Safest**. Loops, suggested walks, **sightseeing tours** (best sights nearby in a
sensible order), navigation with voice, recording, printing and offline use all work on foot.
Build it for an area with `cycleroutes walk` (after `cycleroutes build`).

## Riding context & planning
- **Your ride, your conditions**: bike type (road, gravel, MTB, e-bike, cargo, kids), departure
  time (after dark → lit streets), live wind and heat (Open-Meteo → headwind and shade weighting),
  current road-work closures (City of Austin WZDx feed) and rider hazard reports all change the route.
- **Road choices**: avoid major, secondary or busy roads (measured traffic), stressful streets,
  unpaved surfaces, steps, sidewalks, service roads/parking lots, or trails; and **bike lanes, cycle
  paths & trails only (where possible)**. Protected lanes beside major roads are not "avoided";
  anything unavoidable is reported on the route.
- **Cycle trails**: greenbelt and mountain-bike trails that OSM tags as bike-legal footpaths are
  included; *Trails & greenways* and *Mountain-bike trails* styles; a trails map layer
  (paved / unpaved / MTB grade).
- **Via points** (drag to reshape), **compare all options** side by side, **stops along the way**
  (water, toilets, bike shops, bike share with live bikes, cafés, sights, places to stay) and the
  longest stretch without water, **weather warnings**, **multi-day stages** for long rides.
- **Safer by data**: recorded bike crashes, unsignalised crossings of busy roads, measured traffic
  volumes and noise are shown on every route and used in the scores. A **Family** route that would
  be an absurd detour is relaxed and flagged instead.
- **Community & personal**: press-and-hold the map to report a hazard (pothole, glass, close pass,
  flooding…), rate a street 👍/👎, or save a place; ★ save routes; 🔗 share links that re-plan;
  "route like I usually ride" learns from the routes you actually ride.
- **Print**: overview map (auto or fixed 1:10k/1:25k scale), strip maps for long rides, A6
  handlebar cue card — each with a QR code to the GPX.
- **More**: open-data map layers, the area's low-stress network score, build/switch areas.
- **Offline & local data**: `cycleroutes offline` (or More › *Download offline map*) stores the
  area's vector map on your computer (from the Protomaps OSM build - the public raster tile
  servers forbid bulk downloads); *Save map & data on this device* puts the map, suggested rides,
  layers and your data into the phone/browser so it works with no signal. *Export my data* /
  *Import backup* move rides, places, saved routes and reports between machines as one JSON file.
  Everything the server downloads lives in `data_cache/`.

## GPS riding & tracking
- **Ride this route**: turn-by-turn banner with **voice guidance** (next turn, distance, remaining,
  off-route warning, one-tap reroute), phone screen kept awake, **share live location** link.
- **Record a ride** and **My rides**: GPS track saved (SQLite), GPX/CSV export, the streets you
  actually rode are rated, and a heatmap shows how much of the network you have covered.
- **External GPS**: a USB/serial NMEA receiver (e.g. `hardware/gps_i2c_serial` Arduino sketch):
  `cycleroutes gps` to find/test it, `cycleroutes serve --serial-gps` to offer it in the app.
- **iPhone tracker (pyNav)**: the Pythonista tracker can post to `http://<mac>:8000/location` unchanged.
- **Phone over Wi-Fi**: browsers only allow GPS on HTTPS, so run
  `cycleroutes serve --host 0.0.0.0 --https` and open `https://<your-mac-ip>:8000` (accept the warning once).

## Testing
- `pytest -q` — offline unit/API tests (synthetic street grid; serial GPS via a pseudo-terminal).
- `cycleroutes screenshots --out screenshots` — drives the app in headless Chrome (desktop, phone,
  dark mode, simulated GPS ride), saves numbered screenshots and PDF page renders, runs ~65 checks
  and writes `screenshots/report.html`. Exit code 1 if any check fails.

## Choosing data sources
More › **Data sources** (per area): where the street network comes from (a downloaded
**BBBike extract**, read locally in about a minute, or the live **Overpass** servers), which
**elevation** model to use (USGS 3DEP lidar or Copernicus), and which optional layers feed the
scores (shade, noise, measured traffic, city comfort ratings, crashes, counters, places,
amenities). **Use data already downloaded** reuses any stored download that covers the area
(a new area inside an existing one is simply cut from it - no downloads at all); **Download
fresh copies** refetches everything. Per route, ride settings can score with **all available
data** or **OpenStreetMap only**, and switch rider reports, weather and closures on or off.
From the command line: `cycleroutes build --network extract|overpass --elevation 3dep|copernicus [--refresh]`.

## Data sources (all open; applied where they have coverage)
| What | Source | Coverage |
|---|---|---|
| Streets, paths, bike lanes, speeds, lanes, surface, lighting, signed cycle routes | OpenStreetMap (Overpass) | global |
| Bike shops, water, toilets, repair, parking | OSM amenities | global |
| Cafés, food, sights, places to stay | Overture Maps places | global |
| Elevation | USGS 3DEP bare-earth lidar (US); Copernicus GLO-30 elsewhere | US / global |
| Tree shade | Meta/WRI 1 m canopy height | global |
| Road & aviation noise | US DOT National Transportation Noise Map | US |
| Measured traffic volumes | TxDOT AADT count stations | Texas |
| Bike crashes, city bike-comfort ratings, bike counters, live road works | City of Austin open data | Austin |
| Bike share availability | CapMetro GBFS | Austin |
| Weather | Open-Meteo (free for non-commercial use) | global |
| Basemap / place search | CyclOSM, OpenStreetMap / Nominatim | global |

Not used (need sign-up or aren't open): Strava (API terms), Mapillary and OpenRouteService (need
keys), TxDOT DriveTexas (keyed feed), Garmin/Wahoo (approved developer access).

## Quick start
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/cycleroutes build                     # default: central + north Austin, 6 km radius
.venv/bin/cycleroutes sources                   # (re)apply extra open data to a built area
.venv/bin/cycleroutes offline                   # store the area's map locally (works offline)
.venv/bin/cycleroutes catalog                   # optional: suggested rides
.venv/bin/cycleroutes serve                     # http://127.0.0.1:8000
```
Another region: `cycleroutes build --name bath --lat 51.381 --lon -2.359 --radius 5000`,
then `cycleroutes serve --region bath`. To try it on a phone, serve with `--host 0.0.0.0`
and open `http://<your-mac-ip>:8000` (geolocation needs HTTPS or localhost).

CLI examples:
```bash
cycleroutes route --from 30.2672,-97.7431 --to 30.2489,-97.7700 --pdf route.pdf --gpx route.gpx
cycleroutes loop --start 30.2625,-97.7463 --km 20 --profile scenic --pdf loop.pdf
```

## Limitations (prototype)
- LTS is derived from OSM tags only; missing `maxspeed`/`lanes` fall back to defaults by road class.
- No live or measured traffic volumes or crash data yet (plug-in point: `data/enrich.py`).
- DEM is a 30 m surface model: gradients are approximate, bridges are interpolated.
- Routing uses networkx on one city-sized region; a larger area would need GraphHopper/BRouter with these scores as a custom model.
- Public tile, Overpass and Nominatim servers have usage policies: fine for a prototype, but self-host before going public.
