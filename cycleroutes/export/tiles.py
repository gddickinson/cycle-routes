"""Raster map tiles with an SQLite cache - a Qt-free port of gps-tracker's TileManager.

Used to draw basemaps under printed routes. Returns PIL images instead of QPixmaps.
"""

import io
import logging
import math
import sqlite3
import time
from datetime import datetime

import requests
from PIL import Image

from cycleroutes import config

logger = logging.getLogger(__name__)

TILE_SIZE = 256

TILE_SERVERS = {
    "CyclOSM": {
        "url": "https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
        "subdomains": "abc",
        "attribution": "CyclOSM | Map data © OpenStreetMap contributors",
    },
    "OpenStreetMap": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "subdomains": "",
        "attribution": "© OpenStreetMap contributors",
    },
    "OpenTopoMap": {
        "url": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        "subdomains": "abc",
        "attribution": "OpenTopoMap (CC-BY-SA) | Map data © OpenStreetMap contributors",
    },
}


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Fractional tile x/y (Web Mercator)."""
    n = 2 ** zoom
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_to_lonlat(x: float, y: float, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


class TileManager:
    """Downloads tiles politely (rate-limited, identified) and caches them in SQLite."""

    min_interval_s = 0.1

    def __init__(self, server: str = "CyclOSM", cache_dir=config.DATA_DIR / "tiles"):
        self.server = server
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = cache_dir / "tile_cache.db"
        self._last = 0.0
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS tiles (key TEXT PRIMARY KEY, data BLOB, timestamp TEXT)")

    @property
    def attribution(self) -> str:
        return TILE_SERVERS[self.server]["attribution"]

    def get_tile(self, x: int, y: int, zoom: int) -> Image.Image:
        key = f"{self.server}/{zoom}/{x}/{y}"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT data FROM tiles WHERE key = ?", (key,)).fetchone()
        if row:
            return Image.open(io.BytesIO(row[0])).convert("RGB")
        data = self._download(x, y, zoom)
        if data is None:
            return Image.new("RGB", (TILE_SIZE, TILE_SIZE), (235, 235, 235))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?)",
                         (key, data, datetime.now().isoformat()))
        return Image.open(io.BytesIO(data)).convert("RGB")

    def _download(self, x: int, y: int, zoom: int) -> bytes | None:
        info = TILE_SERVERS[self.server]
        subs = info["subdomains"] or " "
        url = info["url"].format(s=subs[(x + y) % len(subs)].strip(), x=x, y=y, z=zoom)
        wait = self.min_interval_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        try:
            resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=10)
            if resp.status_code == 200:
                return resp.content
            logger.warning("Tile %s -> HTTP %s", url, resp.status_code)
        except requests.RequestException as exc:
            logger.warning("Tile download failed %s: %s", url, exc)
        return None

    def stitch(self, west: float, south: float, east: float, north: float,
               zoom: int) -> tuple[Image.Image, tuple[float, float, float, float]]:
        """Mosaic covering the bbox; returns (image, (x0, y0, x1, y1) in tile units)."""
        fx0, fy0 = lonlat_to_tile(west, north, zoom)
        fx1, fy1 = lonlat_to_tile(east, south, zoom)
        tx0, ty0, tx1, ty1 = int(fx0), int(fy0), int(fx1), int(fy1)
        img = Image.new("RGB", ((tx1 - tx0 + 1) * TILE_SIZE, (ty1 - ty0 + 1) * TILE_SIZE))
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                img.paste(self.get_tile(tx, ty, zoom), ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))
        return img, (tx0, ty0, tx1 + 1, ty1 + 1)


def choose_zoom(west: float, south: float, east: float, north: float,
                max_tiles: int = 30) -> int:
    """Highest zoom (<= 16) whose mosaic of the bbox needs at most max_tiles tiles."""
    for zoom in range(16, 8, -1):
        x0, y0 = lonlat_to_tile(west, north, zoom)
        x1, y1 = lonlat_to_tile(east, south, zoom)
        if (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1) <= max_tiles:
            return zoom
    return 9
