"""Planning endpoints: conditions, stops along a route, stages, map layers, network
score, and building/switching regions."""

import threading
import time
import uuid

from fastapi import APIRouter, Body, HTTPException

from cycleroutes import config
from cycleroutes.api.state import set_state, state
from cycleroutes.data.sources import austin, overture
from cycleroutes.routing.network_score import low_stress_score
from cycleroutes.routing.stages import split_stages
from cycleroutes.routing.stops import along, longest_dry_stretch
from cycleroutes.services import bikeshare, weather

router = APIRouter()
_jobs: dict[str, dict] = {}
_score_cache: dict[str, dict] = {}
EMPTY = {"type": "FeatureCollection", "features": []}


@router.get("/api/conditions")
def conditions(bike: str = "hybrid", depart: str | None = None):
    """Weather, daylight, closures and reports that will shape a ride starting at `depart`."""
    return state().live.context(bike, depart)[1]


@router.get("/api/weather/{rid}")
def ride_weather(rid: str, depart: str | None = None):
    route, _, _ = state().get(rid)
    when = state().live.parse_depart(depart)
    hours = weather.along_ride(state().region.lat, state().region.lon, when, route.time_s / 60)
    return {"hours": hours, "advice": weather.advice(hours)}


def _stop_features() -> list[dict]:
    s = state()
    feats = list(s.amenities["features"]) + list(overture.load(s.region.name)["features"])
    for f in bikeshare.stations()["features"] if austin.covers(*s.region.bbox) else []:
        p = f["properties"]
        feats.append({"geometry": f["geometry"], "properties": {
            "category": "bike_share", "label": "Bike share", "name": p["name"],
            "bikes": p["bikes"], "docks": p["docks"]}})
    return feats


@router.get("/api/stops/{rid}")
def stops(rid: str, within: float = 150):
    route, _, _ = state().get(rid)
    found = along(route, _stop_features(), within)
    return {"stops": found, "longest_without_water_km": longest_dry_stretch(route, found),
            "counts": {g: sum(s["group"] == g for s in found) for g in {s["group"] for s in found}}}


@router.get("/api/stages/{rid}")
def stages(rid: str, km_per_day: float = 60):
    route, _, _ = state().get(rid)
    stays = [f for f in overture.load(state().region.name)["features"] if f["properties"]["category"] == "stay"]
    return split_stages(route, km_per_day, stays)


@router.get("/api/layers/{name}")
def layer(name: str, mode: str = "bike"):
    """Extra map layers from the open-data sources."""
    s = state()
    region = s.region.name
    if name == "crashes":
        pts = austin.load_cached("pedcrashes" if mode == "walk" else "crashes",
                                 region + ("--walk" if mode == "walk" else ""), [])
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
             "properties": {k: c[k] for k in ("date", "severe", "fatal", "where")}} for c in pts]}
    if name == "counters":
        pts = austin.load_cached("counters", region, [])
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
             "properties": {"name": c["name"], "bikes_per_day": c["bikes_per_day"]}} for c in pts]}
    if name == "workzones":
        return s.live.work_zones()
    if name == "bikeshare":
        return bikeshare.stations() if austin.covers(*s.region.bbox) else EMPTY
    if name == "stops":
        return overture.load(region)
    if name == "trails":
        return _trails_geojson(s.region_for(mode))
    if name == "hazards":
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [h["lon"], h["lat"]]},
             "properties": {k: h[k] for k in ("id", "kind", "label", "note", "created", "confirmations")}}
            for h in s.community.hazards()]}
    raise HTTPException(404, f"No layer '{name}'")


_trail_cache: dict[str, dict] = {}


def _trails_geojson(region) -> dict:
    """Off-road trails in the network (one feature per segment), with name, surface and MTB grade."""
    if region.name not in _trail_cache:
        from cycleroutes.scoring import tags
        seen, feats = set(), []
        for u, v, d in region.graph.edges(data=True):
            key = (min(u, v), max(u, v))
            if not d.get("trail") or key in seen:
                continue
            seen.add(key)
            feats.append({"type": "Feature", "geometry": {"type": "LineString",
                          "coordinates": [[round(x, 5), round(y, 5)] for x, y in d["geometry"].coords]},
                          "properties": {"name": (tags.first(d, "name") or "").title(),
                                         "paved": d.get("surface_q", 1) >= 0.6,
                                         "mtb": d.get("mtb_scale"), "km": round(d["length"] / 1000, 2)}})
        _trail_cache[region.name] = {"type": "FeatureCollection", "features": feats}
    return _trail_cache[region.name]


@router.get("/api/network/score")
def network_score():
    name = state().region.name
    if name not in _score_cache:
        _score_cache[name] = low_stress_score(state().region.graph)
    return _score_cache[name]


# --- regions ------------------------------------------------------------------------
@router.get("/api/regions")
def regions():
    active = state().region.name
    return [{"name": p.stem.removeprefix("region_"), "active": p.stem == f"region_{active}"}
            for p in sorted(config.DATA_DIR.glob("region_*.pkl"))]


def _build_job(job: dict, name: str, lat: float, lon: float, radius: float) -> None:
    from cycleroutes.data.region import build_region
    from cycleroutes.routing.catalog import build_catalog
    from cycleroutes.routing.router import Router
    try:
        job["stage"] = "downloading and scoring (this takes 5-30 minutes)"
        region = build_region(name, lat, lon, radius)
        job["stage"] = "generating suggested rides"
        build_catalog(region, Router(region.graph))
        job.update(stage="done", done=True, sources=region.sources)
    except Exception as exc:
        job.update(stage=f"failed: {exc}", done=True, failed=True)


@router.post("/api/regions/build")
def build(body: dict = Body(...)):
    try:
        name = "".join(ch for ch in body["name"].lower() if ch.isalnum() or ch in "-_")
        lat, lon = float(body["lat"]), float(body["lon"])
        radius = min(max(float(body.get("radius_m", 4000)), 1000), 10000)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, "Need name, lat, lon (and optional radius_m <= 10000)") from exc
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"id": job_id, "name": name, "started": time.time(), "stage": "queued", "done": False}
    threading.Thread(target=_build_job, args=(_jobs[job_id], name, lat, lon, radius), daemon=True).start()
    return _jobs[job_id]


@router.get("/api/regions/jobs/{job_id}")
def job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "No such job")
    return _jobs[job_id]


@router.post("/api/regions/{name}/activate")
def activate(name: str):
    if not (config.DATA_DIR / f"region_{name}.pkl").exists():
        raise HTTPException(404, f"Region '{name}' is not built")
    from cycleroutes.api.state import AppState
    set_state(AppState(name))
    return {"active": name}
