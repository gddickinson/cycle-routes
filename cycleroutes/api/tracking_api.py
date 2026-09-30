"""GPS tracking endpoints: live position, ride recording, navigation, iPhone ingest.

Ported from pyNav's iphoneTracking/macbook_server.py (POST /location, same JSON
format as the Pythonista tracker) and gps-tracker's provider manager/logging.
"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from cycleroutes import config
from cycleroutes.api.state import state
from cycleroutes.routing.rating import rate
from cycleroutes.tracking.matching import match_track
from cycleroutes.tracking.nmea import Fix
from cycleroutes.tracking.store import ride_csv, ride_gpx, track_stats

router = APIRouter()


def fix_from_dict(d: dict, source: str = "phone") -> Fix:
    """Accept browser Geolocation-style, our own, or the Pythonista tracker's field names."""
    try:
        lat = float(d.get("latitude", d.get("lat")))
        lon = float(d.get("longitude", d.get("lon")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Each point needs latitude and longitude") from exc
    ts = d.get("timestamp") or d.get("t") or time.time()
    ts = float(ts) / 1000 if float(ts) > 1e11 else float(ts)       # ms -> s
    speed_kmh = d.get("speed_kmh")
    if speed_kmh is None and d.get("speed") is not None and float(d["speed"]) >= 0:
        speed_kmh = float(d["speed"]) * 3.6                          # m/s (browser, iOS)
    heading = d.get("heading", d.get("course"))
    acc = d.get("accuracy_m", d.get("accuracy", d.get("horizontal_accuracy")))
    return Fix(lat, lon, ts, altitude=d.get("altitude", d.get("ele")),
               speed_kmh=speed_kmh, heading=heading if heading is None or heading >= 0 else None,
               accuracy_m=acc, source=d.get("source", source))


# --- Live GPS sources -------------------------------------------------------------
@router.get("/api/gps/sources")
def gps_sources():
    return state().gps.describe()


@router.post("/api/gps/scan")
def gps_scan():
    return {"found": state().gps.scan(), "sources": state().gps.describe()}


@router.post("/api/gps/sources/{key:path}/activate")
def gps_activate(key: str):
    if not state().gps.set_active(key):
        raise HTTPException(404, f"No GPS source '{key}'")
    return state().gps.describe()


@router.get("/api/gps/live")
def gps_live():
    fix = state().gps.latest()
    return {"source": state().gps.active_key, "fix": fix.to_dict() if fix else None}


@router.post("/location")
def iphone_tracker(payload: dict = Body(...)):
    """Drop-in replacement for pyNav's macbook_server: the Pythonista tracker posts here."""
    packets = payload.get("locations") or []
    if not packets:
        raise HTTPException(400, "No sensor data in request")
    s = state()
    source = payload.get("source", "iphone")
    fixes = [fix_from_dict(p, source) for p in packets]
    for f in fixes:
        s.gps.push.push(f)
    open_rides = [r for r in s.rides.rides(limit=20) if r["ended"] is None and r["source"] == source]
    ride_id = open_rides[0]["id"] if open_rides else \
        s.rides.start(f"iPhone ride {datetime.now():%Y-%m-%d %H:%M}", source=source)
    s.rides.add_fixes(ride_id, fixes)
    return {"status": "success", "message": "Sensor data received and processed",
            "packets_received": len(fixes), "source": source, "ride_id": ride_id,
            "transmission_mode": payload.get("transmission_mode", "unknown"), "processed_at": time.time()}


# --- Ride recording ---------------------------------------------------------------
@router.post("/api/rides")
def start_ride(body: dict = Body(default={})):
    name = body.get("name") or f"{'Walk' if body.get('mode') == 'walk' else 'Ride'} {datetime.now():%Y-%m-%d %H:%M}"
    s = state()
    route = s.routes[body["route_id"]][0] if body.get("route_id") in s.routes else None
    mode = route.graph.graph.get("mode", "bike") if route else body.get("mode", "bike")
    ride_id = s.rides.start(name, body.get("source", "phone"), body.get("route_id"), mode)
    if route is not None and mode == "bike":    # learn from the routes you actually choose to ride
        prof = config.PROFILES.get(route.profile)
        if prof:
            s.community.record_choice(route.profile, prof.weights())
    return {"id": ride_id, "name": name}


def _ride_or_404(ride_id: int) -> dict:
    ride = state().rides.ride(ride_id)
    if not ride:
        raise HTTPException(404, "No such ride")
    return ride


@router.post("/api/rides/{ride_id}/points")
def add_points(ride_id: int, body: dict = Body(...)):
    _ride_or_404(ride_id)
    fixes = [fix_from_dict(p) for p in body.get("points", [])]
    if fixes:
        state().gps.push.push(fixes[-1])
    return {"added": state().rides.add_fixes(ride_id, fixes)}


def _summarise(ride_id: int) -> tuple[dict, dict | None]:
    """(summary, matched route payload) for a ride: GPS stats + ratings of the streets used."""
    s = state()
    points = s.rides.points(ride_id)
    summary = track_stats(points)
    mode = (s.rides.ride(ride_id) or {}).get("mode") or "bike"
    try:
        router = s.router_for(mode)
    except HTTPException:
        router = s.router
    matched, coverage = match_track(router, points)
    summary["on_network_pct"] = round(100 * coverage, 1)
    payload = None
    if matched is not None:
        stats = rate(matched)
        summary["ratings"] = stats["ratings"]
        summary["ascent_m"] = stats["ascent_m"]
        summary["lts_pct"] = stats["lts_pct"]
        payload = s.store(matched, stats, "Your ride (streets matched)")
    return summary, payload


@router.post("/api/rides/{ride_id}/finish")
def finish_ride(ride_id: int):
    _ride_or_404(ride_id)
    summary, payload = _summarise(ride_id)
    state().rides.finish(ride_id, json.dumps(summary))
    return {"ride": state().rides.ride(ride_id), "summary": summary, "matched": payload}


@router.get("/api/rides")
def list_rides():
    out = []
    for r in state().rides.rides():
        r["summary"] = json.loads(r["summary"]) if r["summary"] else None
        out.append(r)
    return out


@router.get("/api/rides/{ride_id}.gpx")
def ride_gpx_export(ride_id: int):
    ride = _ride_or_404(ride_id)
    return Response(ride_gpx(ride, state().rides.points(ride_id)), media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="ride-{ride_id}.gpx"'})


@router.get("/api/rides/{ride_id}.csv")
def ride_csv_export(ride_id: int):
    _ride_or_404(ride_id)
    return Response(ride_csv(state().rides.points(ride_id)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="ride-{ride_id}.csv"'})


@router.get("/api/rides/heatmap")
def rides_heatmap():
    """All recorded tracks, plus how much of the street network you have ridden."""
    s = state()
    lines, ridden = [], set()
    for r in s.rides.rides(limit=500):
        pts = s.rides.points(r["id"])
        if len(pts) < 2:
            continue
        lines.append([[p["lon"], p["lat"]] for p in pts[::2]])
        matched, _ = match_track(s.router, pts)
        if matched:
            ridden |= matched.edge_set()
    g = s.region.graph
    ridden_km = sum(min(d["length"] for d in g[u][v].values()) for u, v in ridden if g.has_edge(u, v)) / 1000
    network_km = sum(d["length"] for _, _, d in g.edges(data=True)) / 2000
    return {"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": lines},
            "properties": {"rides": len(lines), "ridden_km": round(ridden_km, 1),
                           "network_km": round(network_km), "coverage_pct": round(100 * ridden_km / max(network_km, 1), 2)}}


# Registered after the .gpx/.csv routes so '/api/rides/3.gpx' isn't read as ride id '3.gpx'.
@router.get("/api/rides/{ride_id}")
def get_ride(ride_id: int):
    ride = _ride_or_404(ride_id)
    points = state().rides.points(ride_id)
    summary, payload = _summarise(ride_id)
    track = {"type": "Feature", "properties": {"name": ride["name"]},
             "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in points]}}
    return {"ride": ride, "summary": summary, "track": track, "matched": payload}


@router.delete("/api/rides/{ride_id}")
def delete_ride(ride_id: int):
    if not state().rides.delete(ride_id):
        raise HTTPException(404, "No such ride")
    return {"deleted": ride_id}


# --- Navigation ---------------------------------------------------------------------
@router.post("/api/navigate/{rid}")
def navigate(rid: str, body: dict = Body(...)):
    """Progress along a planned route for one GPS fix (call on every position update)."""
    nav = state().navigator(rid, restart=bool(body.get("restart")))
    return nav.update(fix_from_dict(body)).to_dict()

