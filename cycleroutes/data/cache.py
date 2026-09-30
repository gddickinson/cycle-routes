"""Reuse data that is already downloaded.

Every download is stored under data_cache/sources/<source>/ together with the area it
covers and when it was fetched. A later request for an area *inside* a cached one is
answered from disk (clipped to the new area) instead of downloading again, as long as
the copy is younger than the source's max age. `refresh=True` forces a new download.
"""

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cycleroutes import config

logger = logging.getLogger(__name__)
ROOT = config.DATA_DIR / "sources"

# How long a download stays usable before it's fetched again (seconds).
MAX_AGE_S = {
    "crashes": 30 * 86400, "bikefacilities": 30 * 86400, "aadt": 180 * 86400, "counters": 7 * 86400,
    "stops": 90 * 86400, "amenities": 30 * 86400, "workzones": 3600, "dem3dep": 3650 * 86400,
    "dem_copernicus": 3650 * 86400, "canopy": 3650 * 86400, "noise": 3650 * 86400,
}


@dataclass
class Hit:
    data: object
    origin: str          # "downloaded" | "cached"
    fetched: float

    def describe(self) -> str:
        when = time.strftime("%Y-%m-%d", time.localtime(self.fetched))
        return "downloaded now" if self.origin == "downloaded" else f"reused download from {when}"


def covers(outer, inner) -> bool:
    s, w, n, e = outer
    s2, w2, n2, e2 = inner
    return s <= s2 and w <= w2 and n >= n2 and e >= e2


def _index(source: str) -> list[dict]:
    path = ROOT / source / "index.json"
    return json.loads(path.read_text()) if path.exists() else []


def find(source: str, bbox) -> dict | None:
    """Newest cached entry for `source` covering bbox and still fresh."""
    max_age = MAX_AGE_S.get(source, 30 * 86400)
    fresh = [e for e in _index(source) if covers(e["bbox"], bbox) and time.time() - e["fetched"] < max_age
             and (ROOT / source / e["file"]).exists()]
    return max(fresh, key=lambda e: e["fetched"]) if fresh else None


def _store(source: str, bbox, suffix: str, write) -> dict:
    folder = ROOT / source
    folder.mkdir(parents=True, exist_ok=True)
    entry = {"file": f"{'_'.join(f'{v:.4f}' for v in bbox)}_{int(time.time())}{suffix}",
             "bbox": list(bbox), "fetched": time.time()}
    write(folder / entry["file"])
    idx = [e for e in _index(source) if not (e["bbox"] == entry["bbox"])] + [entry]
    (folder / "index.json").write_text(json.dumps(idx, indent=1))
    return entry


# --- clipping helpers --------------------------------------------------------------
def clip_points(items: list[dict], bbox) -> list[dict]:
    s, w, n, e = bbox
    return [p for p in items if s <= p["lat"] <= n and w <= p["lon"] <= e]


def clip_geojson(geo: dict, bbox) -> dict:
    s, w, n, e = bbox

    def inside(coords) -> bool:
        if coords and isinstance(coords[0], (int, float)):
            return s <= coords[1] <= n and w <= coords[0] <= e
        return any(inside(c) for c in coords)
    feats = [f for f in geo.get("features", []) if f.get("geometry") and inside(f["geometry"]["coordinates"])]
    return {**geo, "features": feats}


# --- public API -------------------------------------------------------------------
def json_source(source: str, bbox, fetch, clip=None, refresh: bool = False, prefer_cached: bool = True) -> Hit:
    """JSON data for bbox: from a covering cached download when possible, else fetch(bbox)."""
    if prefer_cached and not refresh:
        hit = find(source, bbox)
        if hit:
            data = json.loads((ROOT / source / hit["file"]).read_text())
            logger.info("%s: reusing download from %s", source, time.ctime(hit["fetched"]))
            return Hit(clip(data, bbox) if clip else data, "cached", hit["fetched"])
    data = fetch(bbox)
    entry = _store(source, bbox, ".json", lambda p: p.write_text(json.dumps(data)))
    return Hit(data, "downloaded", entry["fetched"])


def array_source(source: str, bbox, fetch, save, load, refresh: bool = False, prefer_cached: bool = True) -> Hit:
    """Raster-like data (saved with save(obj, path) / load(path)) with the same reuse rules."""
    if prefer_cached and not refresh:
        hit = find(source, bbox)
        if hit:
            logger.info("%s: reusing download from %s", source, time.ctime(hit["fetched"]))
            return Hit(load(ROOT / source / hit["file"]), "cached", hit["fetched"])
    obj = fetch(bbox)
    entry = _store(source, bbox, ".npz", lambda p: save(obj, p))
    return Hit(obj, "downloaded", entry["fetched"])


def summary() -> list[dict]:
    """Everything downloaded so far: source, area, age, size (for the UI)."""
    out = []
    for folder in sorted(ROOT.glob("*")) if ROOT.exists() else []:
        for e in _index(folder.name):
            p = folder / e["file"]
            if p.exists():
                out.append({"source": folder.name, "bbox": e["bbox"], "fetched": e["fetched"],
                            "mb": round(p.stat().st_size / 1e6, 2)})
    return out


def save_npz(path: Path, **arrays) -> None:
    with open(path, "wb") as fh:          # np.savez_compressed would append ".npz" to a str path
        np.savez_compressed(fh, **arrays)
