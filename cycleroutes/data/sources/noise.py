"""Road + aviation noise (US DOT National Transportation Noise Map, 2022).

The service is published as colour-coded map tiles; the legend gives the colour of
each decibel band, so pixels are decoded back into approximate dB(A) levels.
"""

import base64
import io
import logging
import math

import numpy as np
import requests
from PIL import Image

from cycleroutes import config

logger = logging.getLogger(__name__)
ZOOM = 12          # deepest cached level (~38 m pixels at Austin's latitude)
QUIET_DB = 40.0    # transparent pixels: below the lowest mapped band (45 dB)


def _band_mid(label: str) -> float:
    label = label.strip()
    if label.startswith(">"):
        return float(label[1:]) + 2.5
    lo, hi = (float(v) for v in label.split("-"))
    return (lo + hi) / 2


def legend_colours() -> list[tuple[tuple[int, int, int], float]]:
    """[(rgb, dB)] from the service legend swatches."""
    data = requests.get(f"{config.NOISE_TILE_URL}/legend?f=json", timeout=60,
                        headers={"User-Agent": config.USER_AGENT}).json()
    image_layer = next(l for l in data["layers"] if l.get("layerName") == "Image")
    out = []
    for item in image_layer["legend"]:
        sw = Image.open(io.BytesIO(base64.b64decode(item["imageData"]))).convert("RGBA")
        r, g, b, _ = sw.getpixel((sw.width // 2, sw.height // 2))
        out.append(((r, g, b), _band_mid(item["label"])))
    return out


def _tile_xy(lat, lon, z):
    n = 2 ** z
    return ((lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


class NoiseGrid:
    """dB(A) mosaic in tile-pixel space at ZOOM."""

    def __init__(self, db: np.ndarray, px0: float, py0: float):
        self.db, self.px0, self.py0 = db, px0, py0

    def sample(self, lons, lats) -> np.ndarray:
        out = []
        for lon, lat in zip(lons, lats):
            tx, ty = _tile_xy(lat, lon, ZOOM)
            c, r = int(tx * 256 - self.px0), int(ty * 256 - self.py0)
            r = min(max(r, 0), self.db.shape[0] - 1)
            c = min(max(c, 0), self.db.shape[1] - 1)
            out.append(self.db[r, c])
        return np.array(out)


def fetch_noise(south, west, north, east) -> NoiseGrid:
    colours = legend_colours()
    palette = np.array([c for c, _ in colours], dtype=float)
    levels = np.array([d for _, d in colours])
    fx0, fy0 = _tile_xy(north, west, ZOOM)
    fx1, fy1 = _tile_xy(south, east, ZOOM)
    x0, y0, x1, y1 = int(fx0), int(fy0), int(fx1), int(fy1)
    db = np.full(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), QUIET_DB, dtype=np.float32)
    session = requests.Session()
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            resp = session.get(f"{config.NOISE_TILE_URL}/tile/{ZOOM}/{y}/{x}", timeout=60,
                               headers={"User-Agent": config.USER_AGENT})
            if resp.status_code != 200 or not resp.content.startswith(b"\x89PNG"):
                continue
            rgba = np.asarray(Image.open(io.BytesIO(resp.content)).convert("RGBA"), dtype=float)
            opaque = rgba[..., 3] > 128
            dist = ((rgba[..., None, :3] - palette[None, None]) ** 2).sum(-1)
            tile_db = np.where(opaque, levels[dist.argmin(-1)], QUIET_DB)
            db[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = tile_db
    logger.info("Noise grid %s px; %.0f%% of area above 60 dB", db.shape, 100 * (db >= 60).mean())
    return NoiseGrid(db, x0 * 256, y0 * 256)
