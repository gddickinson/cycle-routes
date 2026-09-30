"""Download a region's vector basemap once and store it locally (SQLite).

Source: the Protomaps daily build of OpenStreetMap (a single PMTiles archive, ODbL),
read with HTTP range requests so only the region's tiles are downloaded. Unlike the
public raster tile servers (whose usage policies forbid bulk downloading), this build
is published for extracting areas. Tiles are then served by our own API, so maps
work without internet and can be saved onto a phone for offline riding.
"""

import json
import logging
import math
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import requests
from pmtiles.reader import Reader

from cycleroutes import config

logger = logging.getLogger(__name__)
WORKERS = 8


def basemap_path(region: str) -> Path:
    return config.DATA_DIR / f"basemap_{region}.sqlite"


def latest_build_url() -> str:
    builds = requests.get(config.PROTOMAPS_BUILDS_URL, timeout=30,
                          headers={"User-Agent": config.USER_AGENT}).json()
    return config.PROTOMAPS_BUILD_URL.format(key=builds[-1]["key"])


class _HttpRanges:
    """get_bytes(offset, length) over HTTP, caching the (small, reused) directory reads."""

    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT

    @lru_cache(maxsize=256)
    def get(self, offset: int, length: int) -> bytes:
        for attempt in range(4):
            try:
                r = self.session.get(self.url, timeout=60,
                                     headers={"Range": f"bytes={offset}-{offset + length - 1}"})
                if r.status_code in (200, 206):
                    return r.content
            except requests.RequestException:
                pass
            time.sleep(2 * (attempt + 1))
        raise RuntimeError("Basemap source unavailable")


def tiles_for_bbox(south: float, west: float, north: float, east: float, z: int):
    n = 2 ** z

    def xy(lat, lon):
        return (int((lon + 180) / 360 * n),
                int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))
    x0, y0 = xy(north, west)
    x1, y1 = xy(south, east)
    return [(x, y) for x in range(max(x0, 0), min(x1, n - 1) + 1) for y in range(max(y0, 0), min(y1, n - 1) + 1)]


def download_basemap(region: str, bbox, max_zoom: int = config.OFFLINE_MAX_ZOOM,
                     progress=None) -> dict:
    """Extract the region's tiles (zoom 0..max_zoom) into data_cache/basemap_<region>.sqlite."""
    url = latest_build_url()
    src = _HttpRanges(url)
    reader = Reader(src.get)
    header, metadata = reader.header(), reader.metadata()
    pad = 0.02
    s, w, n, e = bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad
    todo = [(z, x, y) for z in range(0, max_zoom + 1) for x, y in tiles_for_bbox(s, w, n, e, z)]
    path = basemap_path(region)
    tmp = path.with_suffix(".partial")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute("CREATE TABLE tiles (z INTEGER, x INTEGER, y INTEGER, data BLOB, PRIMARY KEY (z, x, y))")
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    stored = size = done = 0
    with ThreadPoolExecutor(WORKERS) as pool:       # tiles are independent HTTP range reads
        for (z, x, y), data in zip(todo, pool.map(lambda t: reader.get(*t), todo)):
            done += 1
            if data:
                db.execute("INSERT INTO tiles VALUES (?,?,?,?)", (z, x, y, data))
                stored += 1
                size += len(data)
            if progress and (done % 25 == 0 or done == len(todo)):
                progress(done, len(todo))
    info = {"source": url, "built": time.time(), "tiles": stored, "bytes": size, "max_zoom": max_zoom,
            "bbox": [s, w, n, e], "compression": int(header["tile_compression"].value),
            "attribution": "© OpenStreetMap contributors, Protomaps"}
    db.executemany("INSERT INTO meta VALUES (?, ?)",
                   [("info", json.dumps(info)), ("metadata", json.dumps(metadata))])
    db.commit()
    db.close()
    tmp.replace(path)
    logger.info("Offline basemap: %d tiles, %.1f MB", stored, size / 1e6)
    return info


class LocalBasemap:
    """Read-only access to a downloaded basemap (thread-safe)."""

    def __init__(self, region: str):
        self.path = basemap_path(region)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False) if self.path.exists() else None

    @property
    def available(self) -> bool:
        return self._db is not None

    def info(self) -> dict | None:
        if not self._db:
            return None
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'info'").fetchone()
        return json.loads(row[0]) if row else None

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        if not self._db:
            return None
        with self._lock:
            row = self._db.execute("SELECT data FROM tiles WHERE z = ? AND x = ? AND y = ?", (z, x, y)).fetchone()
        return row[0] if row else None

    def tile_list(self, min_zoom: int = 0) -> list[tuple[int, int, int]]:
        with self._lock:
            return self._db.execute("SELECT z, x, y FROM tiles WHERE z >= ? ORDER BY z", (min_zoom,)).fetchall()
