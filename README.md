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

## GPS riding & tracking
- **Ride this route**: turn-by-turn banner (next turn, distance, remaining, off-route warning, one-tap
  reroute), phone screen kept awake. Uses the phone's own GPS in the browser.
- **Record a ride** and **My rides**: GPS track saved (SQLite), GPX/CSV export, and the streets you
  actually rode are rated for safety, fun, traffic and hills.
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

## Data sources
| What | Source |
|---|---|
| Streets, paths, bike lanes, speed limits, lanes, surface, lighting | OpenStreetMap via Overpass (osmnx) |
| Regional/national signed cycle routes (the "cycle map") | OSM `route=bicycle` relations (lcn/rcn/ncn/icn) |
| Parks, water, woods, viewpoints | OSM features |
| Elevation | Copernicus GLO-30 DEM (AWS open data) |
| Basemap | CyclOSM / OpenStreetMap tiles |
| Place search | Nominatim |
| Bike shops, water, toilets, repair, parking, bike share | OSM amenities |

## Quick start
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/cycleroutes build                     # default: central + north Austin, 6 km radius
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
