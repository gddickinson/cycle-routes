"""Build (download + enrich + cache) and load a scored cycling region."""

import logging
import pickle
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import networkx as nx

from cycleroutes import config
from cycleroutes.data import amenities, cycle_networks, elevation, enrich, osm_network

logger = logging.getLogger(__name__)


@dataclass
class Region:
    name: str
    lat: float
    lon: float
    radius_m: float
    graph: nx.MultiDiGraph
    features: gpd.GeoDataFrame

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(south, west, north, east) of the network's nodes."""
        ys = [d["y"] for _, d in self.graph.nodes(data=True)]
        xs = [d["x"] for _, d in self.graph.nodes(data=True)]
        return min(ys), min(xs), max(ys), max(xs)


def region_path(name: str) -> Path:
    return config.DATA_DIR / f"region_{name}.pkl"


def build_region(name: str, lat: float, lon: float, radius_m: float) -> Region:
    """Fetch every data source for a region, score it and cache it to disk."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    graph = osm_network.download_bike_network(lat, lon, radius_m)
    features = osm_network.download_scenic_features(lat, lon, radius_m)
    region = Region(name, lat, lon, radius_m, graph, features)

    south, west, north, east = region.bbox
    dem_cache = config.DATA_DIR / f"dem_{name}.npz"
    if dem_cache.exists():
        grid = elevation.ElevationGrid.load(dem_cache)
    else:
        grid = elevation.fetch_elevation_grid(south, west, north, east)
        grid.save(dem_cache)
    route_ways = cycle_networks.fetch_cycle_route_ways(south, west, north, east)

    enrich.enrich(graph, features, grid, route_ways)
    try:
        amenities.fetch_amenities(name, region.bbox)
    except RuntimeError as exc:
        logger.warning("Amenities unavailable: %s", exc)
    with open(region_path(name), "wb") as fh:
        pickle.dump(region, fh, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Region '%s' saved to %s", name, region_path(name))
    return region


def load_region(name: str) -> Region:
    path = region_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"Region '{name}' not built yet - run: python -m cycleroutes.cli build --name {name}")
    with open(path, "rb") as fh:
        return pickle.load(fh)
