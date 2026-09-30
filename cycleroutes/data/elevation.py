"""Elevation from the Copernicus GLO-30 DEM: fetch once per region, sample locally.

The DEM is a surface model (it includes buildings/trees) and passes *under*
bridges, so callers should smooth profiles and treat bridges specially.
"""

import logging
import math
from pathlib import Path

import numpy as np
import rasterio
from numpy.lib.stride_tricks import sliding_window_view
from rasterio.merge import merge

from cycleroutes import config

logger = logging.getLogger(__name__)


class ElevationGrid:
    """An in-memory DEM window with bilinear sampling in lon/lat."""

    def __init__(self, data: np.ndarray, west: float, north: float, res_x: float, res_y: float):
        self.data = data.astype(np.float32)
        self.west, self.north = west, north
        self.res_x, self.res_y = res_x, res_y

    def sample(self, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
        """Bilinear elevation (m) at arrays of lon/lat."""
        col = (np.asarray(lons) - self.west) / self.res_x - 0.5
        row = (self.north - np.asarray(lats)) / self.res_y - 0.5
        h, w = self.data.shape
        c0 = np.clip(np.floor(col).astype(int), 0, w - 2)
        r0 = np.clip(np.floor(row).astype(int), 0, h - 2)
        fc = np.clip(col - c0, 0, 1)
        fr = np.clip(row - r0, 0, 1)
        d = self.data
        top = d[r0, c0] * (1 - fc) + d[r0, c0 + 1] * fc
        bot = d[r0 + 1, c0] * (1 - fc) + d[r0 + 1, c0 + 1] * fc
        return top * (1 - fr) + bot * fr

    def covers(self, south: float, west: float, north: float, east: float) -> bool:
        h, w = self.data.shape
        return (self.west <= west and self.north >= north
                and self.west + w * self.res_x >= east and self.north - h * self.res_y <= south)

    def save(self, path: Path) -> None:
        np.savez_compressed(path, data=self.data,
                            meta=np.array([self.west, self.north, self.res_x, self.res_y]))

    @classmethod
    def load(cls, path: Path) -> "ElevationGrid":
        f = np.load(path)
        west, north, rx, ry = f["meta"]
        return cls(f["data"], west, north, rx, ry)


def _window_filter(data: np.ndarray, size: int, fn) -> np.ndarray:
    pad = size // 2
    padded = np.pad(data, pad, mode="edge")
    return fn(sliding_window_view(padded, (size, size)), axis=(-2, -1))


def surface_to_terrain(data: np.ndarray, size: int = config.DEM_OPENING_PX) -> np.ndarray:
    """Approximate bare-earth heights from a surface model.

    Buildings and tree canopy are narrow bumps, so a morphological opening
    (min filter then max filter) removes them; a 3x3 mean then smooths the rest.
    """
    opened = _window_filter(_window_filter(data, size, np.min), size, np.max)
    return _window_filter(opened, 3, np.mean)


def _tile_urls(south: float, west: float, north: float, east: float) -> list[str]:
    urls = []
    for lat in range(math.floor(south), math.floor(north) + 1):
        for lon in range(math.floor(west), math.floor(east) + 1):
            urls.append(config.COPERNICUS_DEM_URL.format(
                ns="N" if lat >= 0 else "S", lat=abs(lat),
                ew="E" if lon >= 0 else "W", lon=abs(lon)))
    return urls


def fetch_elevation_grid(south: float, west: float, north: float, east: float) -> ElevationGrid:
    """Download (range-read) the DEM covering the bbox, padded by ~300 m."""
    pad = 0.003
    bounds = (west - pad, south - pad, east + pad, north + pad)
    datasets = []
    for url in _tile_urls(*[bounds[1], bounds[0], bounds[3], bounds[2]]):
        try:
            datasets.append(rasterio.open(url))
        except rasterio.errors.RasterioIOError:
            logger.info("No DEM tile (ocean?) at %s", url)
    if not datasets:
        raise RuntimeError("No elevation data covers this region")
    try:
        mosaic, transform = merge(datasets, bounds=bounds)
    finally:
        for ds in datasets:
            ds.close()
    logger.info("DEM window %s px; removing buildings/canopy", mosaic.shape[1:])
    return ElevationGrid(surface_to_terrain(mosaic[0].astype(np.float32)), transform.c, transform.f, transform.a, -transform.e)


def climb_along(elevations: np.ndarray, threshold: float = config.CLIMB_NOISE_THRESHOLD_M) -> tuple[float, float]:
    """(ascent, descent) in metres along a profile, ignoring wiggles < threshold."""
    ascent = descent = 0.0
    if len(elevations) < 2:
        return ascent, descent
    anchor = float(elevations[0])
    for z in elevations[1:]:
        dz = float(z) - anchor
        if dz >= threshold:
            ascent += dz
            anchor = float(z)
        elif dz <= -threshold:
            descent -= dz
            anchor = float(z)
    return ascent, descent
