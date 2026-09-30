"""USGS 3DEP bare-earth elevation (lidar-derived, US only) via the public ImageServer.

Unlike the Copernicus surface model this is bare earth (no buildings or trees),
so it needs no building-removal filter.
"""

import io
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
import requests

from cycleroutes import config
from cycleroutes.data.elevation import ElevationGrid

logger = logging.getLogger(__name__)
CHUNK_PX = 500
WORKERS = 4
RETRIES = 4
US_BBOX = (18.0, -179.0, 72.0, -65.0)


def _get_with_retry(params: dict) -> requests.Response:
    """The public ImageServer returns sporadic 502/503s under load; back off and retry."""
    for attempt in range(RETRIES):
        try:
            resp = requests.get(config.USGS_3DEP_URL, params=params, timeout=180,
                                headers={"User-Agent": config.USER_AGENT})
            if resp.ok and resp.content[:2] in (b"II", b"MM"):
                return resp
            logger.warning("3DEP HTTP %s (attempt %d)", resp.status_code, attempt + 1)
        except requests.RequestException as exc:
            logger.warning("3DEP request failed (attempt %d): %s", attempt + 1, exc)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("3DEP elevation service unavailable")


def covers(south: float, west: float, north: float, east: float) -> bool:
    s, w, n, e = US_BBOX
    return s <= south and north <= n and w <= west and east <= e


def fetch_3dep_grid(south: float, west: float, north: float, east: float,
                    res_m: float = config.DEM_3DEP_RES_M) -> ElevationGrid:
    """Mosaic of 3DEP elevation over the bbox (lon/lat grid, ~res_m pixels)."""
    pad = 0.003
    south, west, north, east = south - pad, west - pad, north + pad, east + pad
    deg_y = res_m / 111_320
    deg_x = res_m / (111_320 * math.cos(math.radians((south + north) / 2)))
    width, height = math.ceil((east - west) / deg_x), math.ceil((north - south) / deg_y)
    grid = np.full((height, width), np.nan, dtype=np.float32)

    def fetch_chunk(r0: int, c0: int) -> None:
        h, w = min(CHUNK_PX, height - r0), min(CHUNK_PX, width - c0)
        bb = (west + c0 * deg_x, north - (r0 + h) * deg_y, west + (c0 + w) * deg_x, north - r0 * deg_y)
        params = {"bbox": ",".join(f"{v:.7f}" for v in bb), "bboxSR": 4326, "imageSR": 4326,
                  "size": f"{w},{h}", "format": "tiff", "pixelType": "F32",
                  "interpolation": "RSP_BilinearInterpolation", "f": "image"}
        with rasterio.open(io.BytesIO(_get_with_retry(params).content)) as ds:
            grid[r0:r0 + h, c0:c0 + w] = ds.read(1)[:h, :w]

    chunks = [(r0, c0) for r0 in range(0, height, CHUNK_PX) for c0 in range(0, width, CHUNK_PX)]
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(lambda rc: fetch_chunk(*rc), chunks))
    bad = ~np.isfinite(grid) | (grid < -500)
    if bad.all():
        raise RuntimeError("3DEP returned no data for this area")
    grid[bad] = np.nanmedian(grid[~bad])
    logger.info("3DEP bare-earth DEM %sx%s px at %.0f m", width, height, res_m)
    return ElevationGrid(grid, west, north, deg_x, deg_y)
