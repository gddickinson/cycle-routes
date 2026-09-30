"""Data-source options for the current area: what's available, what's used, what's
already downloaded - and applying changes (re-scoring or rebuilding) in the background."""

import threading
import time
import uuid

from fastapi import APIRouter, Body, HTTPException

from cycleroutes.api.state import AppState, set_state, state
from cycleroutes.data import cache, extract, settings
from cycleroutes.data.sources import austin, txdot_aadt, usgs_3dep

router = APIRouter()
_jobs: dict[str, dict] = {}


def _availability(bbox) -> dict:
    in_austin, in_texas, in_us = austin.covers(*bbox), txdot_aadt.covers(*bbox), usgs_3dep.covers(*bbox)
    return {"canopy": True, "stops": True, "amenities": True, "noise": in_us, "aadt": in_texas,
            "comfort": in_austin, "crashes": in_austin, "counters": in_austin}


@router.get("/api/sources")
def sources():
    s = state()
    region, bbox = s.region, s.region.bbox
    opts = settings.load(region.name)
    avail = _availability(bbox)
    ex = extract.extract_for(*bbox)
    ex_path = extract.local_path(ex) if ex else None
    report = getattr(region, "sources", {})
    return {
        "area": region.name,
        "settings": opts,
        "network": {"current": report.get("network", "unknown"), "choice": opts["network"],
                    "options": {"auto": "Automatic (extract if available, else live)",
                                "extract": f"Downloaded extract{f' ({ex['provider']} {ex['name']})' if ex else ' (none covers this area)'}",
                                "overpass": "Live OpenStreetMap servers (Overpass)"},
                    "extract_available": bool(ex),
                    "extract_file": ex_path and ex_path.exists() and {
                        "name": ex_path.name, "mb": round(ex_path.stat().st_size / 1e6, 1),
                        "downloaded": ex_path.stat().st_mtime}},
        "elevation": {"choice": opts["elevation"], "current": report.get("elevation", "unknown"),
                      "options": {"auto": "Automatic (best available)",
                                  "3dep": "USGS 3DEP lidar, bare earth (US only)" + ("" if usgs_3dep.covers(*bbox) else " - not available here"),
                                  "copernicus": "Copernicus GLO-30 (global, 30 m)"}},
        "layers": [{"key": k, "label": label, "enabled": opts["layers"].get(k, True), "available": avail[k],
                    "status": report.get(k, "")} for k, label in settings.LAYERS.items()],
        "downloads": sorted(cache.summary(), key=lambda d: -d["fetched"]),
        "live": ["Weather: Open-Meteo", "Road works: City of Austin WZDx" if austin.covers(*bbox) else None,
                 "Bike share: CapMetro GBFS" if austin.covers(*bbox) else None, "Rider reports (this app)"],
    }


def _apply_job(job: dict, name: str, rebuild: bool, refresh: bool) -> None:
    from cycleroutes.data.region import build_region, load_region, save_region
    from cycleroutes.data.sources.apply import apply_all
    from cycleroutes.routing.catalog import build_catalog
    from cycleroutes.routing.router import Router
    try:
        if rebuild:
            old = load_region(name)
            job["stage"] = "rebuilding the street network"
            region = build_region(name, old.lat, old.lon, old.radius_m, refresh=refresh)
        else:
            job["stage"] = "applying data sources"
            region = load_region(name)
            apply_all(region, refresh=refresh)
            save_region(region)
        job["stage"] = "updating suggested rides"
        build_catalog(region, Router(region.graph))
        set_state(AppState(name))
        job.update(stage="done", done=True, report=region.sources)
    except Exception as exc:
        job.update(stage=f"failed: {type(exc).__name__}: {exc}", done=True, failed=True)


@router.post("/api/sources")
def update_sources(body: dict = Body(...)):
    """Save choices; with apply=true re-score (or rebuild if the network source changed)."""
    name = state().region.name
    before = settings.load(name)
    try:
        after = settings.save(name, body.get("settings", {}))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not body.get("apply"):
        return {"settings": after}
    rebuild = after["network"] != before["network"] or bool(body.get("rebuild"))
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"id": job_id, "started": time.time(), "stage": "queued", "done": False, "rebuild": rebuild}
    threading.Thread(target=_apply_job, args=(_jobs[job_id], name, rebuild, bool(body.get("refresh"))),
                     daemon=True).start()
    return {"settings": after, "job": _jobs[job_id]}


@router.get("/api/sources/jobs/{job_id}")
def job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "No such job")
    return _jobs[job_id]

