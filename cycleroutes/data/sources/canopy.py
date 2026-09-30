"""Tree-canopy shade from the Meta/WRI 1 m global canopy-height map (AWS open data)."""

import logging
import math

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform

from cycleroutes import config

logger = logging.getLogger(__name__)
TILE_ZOOM = 10
SAMPLE_RES_M = 2.0


def _quadkey(x: int, y: int, z: int) -> str:
    return "".join(str((1 if x >> i & 1 else 0) + (2 if y >> i & 1 else 0)) for i in range(z - 1, -1, -1))


def _tiles(south, west, north, east):
    n = 2 ** TILE_ZOOM

    def xy(lat, lon):
        return (int((lon + 180) / 360 * n),
                int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n))
    x0, y0 = xy(north, west)
    x1, y1 = xy(south, east)
    return [_quadkey(x, y, TILE_ZOOM) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


class CanopyGrid:
    """Canopy height (m) over a region, in Web Mercator, sampled by lon/lat."""

    def __init__(self, data: np.ndarray, transform_, crs):
        self.data, self.transform, self.crs = data, transform_, crs

    def heights(self, lons, lats) -> np.ndarray:
        xs, ys = transform("EPSG:4326", self.crs, list(lons), list(lats))
        inv = ~self.transform
        cols, rows = inv * (np.array(xs), np.array(ys))
        rows = np.clip(rows.astype(int), 0, self.data.shape[0] - 1)
        cols = np.clip(cols.astype(int), 0, self.data.shape[1] - 1)
        return self.data[rows, cols]


def fetch_canopy(south, west, north, east) -> CanopyGrid:
    """Read (at ~2 m) the canopy tiles covering the bbox."""
    datasets = [rasterio.open(config.CANOPY_TILE_URL.format(quadkey=q)) for q in _tiles(south, west, north, east)]
    try:
        xs, ys = transform("EPSG:4326", datasets[0].crs, [west, east], [south, north])
        data, tf = merge(datasets, bounds=(xs[0], ys[0], xs[1], ys[1]), res=SAMPLE_RES_M)
        crs = datasets[0].crs
    finally:
        for ds in datasets:
            ds.close()
    logger.info("Canopy grid %s px, %.0f%% tree cover", data.shape[1:], 100 * (data[0] > config.CANOPY_TREE_M).mean())
    return CanopyGrid(data[0], tf, crs)
