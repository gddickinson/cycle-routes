"""Offline map tiles, offline status/manifest, basemap download jobs, data backup."""

import threading
import time
import uuid

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from cycleroutes import config
from cycleroutes.api.state import state
from cycleroutes.offline import backup
from cycleroutes.offline.basemap import LocalBasemap, download_basemap

router = APIRouter()
_jobs: dict[str, dict] = {}
_basemaps: dict[str, LocalBasemap] = {}
# Exactly the URLs the page requests, so the service worker can answer them offline.
PRECACHE_API = ["/api/region", "/api/offline/status", "/api/gps/sources", "/api/conditions?bike=hybrid",
                "/api/amenities", "/api/hazard-types", "/api/places", "/api/favourites", "/api/rides",
                "/api/network/score", "/api/sources", "/api/stop-types"]
PER_MODE = ["/api/network?mode={m}", "/api/suggested?mode={m}", "/api/layers/trails?mode={m}",
            "/api/layers/crashes?mode={m}", "/api/layers/stops?mode={m}", "/api/layers/counters?mode={m}"]


def _basemap() -> LocalBasemap:
    name = state().region.name
    if name not in _basemaps or not _basemaps[name].available:
        _basemaps[name] = LocalBasemap(name)
    return _basemaps[name]


@router.get("/tiles/{z}/{x}/{y}.mvt")
def tile(z: int, x: int, y: int):
    bm = _basemap()
    data = bm.tile(z, x, y) if bm.available else None
    if data is None:
        return Response(status_code=204)
    headers = {"Cache-Control": "public, max-age=604800"}
    if (bm.info() or {}).get("compression") == 2:
        headers["Content-Encoding"] = "gzip"
    return Response(data, media_type="application/vnd.mapbox-vector-tile", headers=headers)


def _region_mb() -> float:
    name = state().region.name
    return round(sum(p.stat().st_size for p in config.DATA_DIR.glob(f"*_{name}.*")) / 1e6, 1)


@router.get("/api/offline/status")
def status():
    info = _basemap().info()
    return {"region": state().region.name, "region_data_mb": _region_mb(),
            "basemap": info and {k: info[k] for k in ("tiles", "bytes", "max_zoom", "built", "source", "attribution")}}


@router.get("/api/offline/manifest")
def manifest(min_zoom: int = 10):
    """URLs to save on a device for offline use: basemap tiles + the app's data."""
    bm = _basemap()
    if not bm.available:
        raise HTTPException(404, "Download the offline map first")
    tiles = [f"/tiles/{z}/{x}/{y}.mvt" for z, x, y in bm.tile_list(min_zoom)]
    modes = ["bike", "walk"] if state().walk_available else ["bike"]
    return {"tiles": tiles, "api": PRECACHE_API + [u.format(m=m) for m in modes for u in PER_MODE]}


def _run(job: dict, name: str, bbox, max_zoom: int) -> None:
    try:
        def progress(i, n):
            job.update(done_tiles=i, total_tiles=n, stage=f"downloading map tiles {i}/{n}")
        info = download_basemap(name, bbox, max_zoom, progress)
        _basemaps.pop(name, None)
        job.update(stage="done", done=True, info={k: info[k] for k in ("tiles", "bytes")})
    except Exception as exc:
        job.update(stage=f"failed: {exc}", done=True, failed=True)


@router.post("/api/offline/basemap")
def start_download(max_zoom: int = config.OFFLINE_MAX_ZOOM):
    s = state()
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"id": job_id, "started": time.time(), "stage": "starting", "done": False}
    threading.Thread(target=_run, args=(_jobs[job_id], s.region.name, s.region.bbox, min(max_zoom, 15)),
                     daemon=True).start()
    return _jobs[job_id]


@router.get("/api/offline/jobs/{job_id}")
def job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(404, "No such job")
    return _jobs[job_id]


@router.get("/api/backup")
def export_backup():
    data = backup.export_json(state().rides_db_path)
    return Response(backup.dumps(data), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="cycleroutes-backup.json"'})


@router.post("/api/backup")
def import_backup(data: dict = Body(...)):
    try:
        return {"imported": backup.import_json(state().rides_db_path, data)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Could not import: {exc}") from exc
