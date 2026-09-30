"""Build (download + enrich + cache) and load a scored cycling region.

Where the street network comes from is chosen per area (data/settings.py):
  1. reuse   - an already-built area that covers this one is cut down (keeps all scores);
  2. extract - a downloaded OSM extract file (e.g. BBBike, weekly), read locally;
  3. overpass - live Overpass API queries.
"""

import json
import logging
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox

from cycleroutes import config
from cycleroutes.data import cache, cycle_networks, elevation, enrich, osm_network, settings

logger = logging.getLogger(__name__)
EXTRACT_MAX_AGE_S = 8 * 86400     # BBBike extracts are rebuilt weekly


@dataclass
class Region:
    name: str
    lat: float
    lon: float
    radius_m: float
    graph: nx.MultiDiGraph
    features: gpd.GeoDataFrame
    sources: dict = field(default_factory=dict)   # which data sources were used, and how

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(south, west, north, east) of the network's nodes."""
        ys = [d["y"] for _, d in self.graph.nodes(data=True)]
        xs = [d["x"] for _, d in self.graph.nodes(data=True)]
        return min(ys), min(xs), max(ys), max(xs)


def region_path(name: str) -> Path:
    return config.DATA_DIR / f"region_{name}.pkl"


def _index_path() -> Path:
    return config.DATA_DIR / "regions.json"


def region_index() -> dict:
    p = _index_path()
    index = json.loads(p.read_text()) if p.exists() else {}
    return {k: v for k, v in index.items() if region_path(k).exists()}


def requested_bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    west, south, east, north = ox.utils_geo.bbox_from_point((lat, lon), dist=radius_m)
    return south, west, north, east


def find_covering_region(bbox, exclude: str | None = None) -> str | None:
    """Smallest already-built area whose network covers bbox."""
    hits = [(name, v) for name, v in region_index().items()
            if name != exclude and "--" not in name and cache.covers(v["bbox"], bbox)]
    if not hits:
        return None
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])   # noqa: E731
    return min(hits, key=lambda h: area(h[1]["bbox"]))[0]


def _cut_from(parent: Region, name: str, lat: float, lon: float, radius_m: float, bbox) -> Region:
    from cycleroutes.data.amenities import amenities_path
    from cycleroutes.data.sources import austin
    s, w, n, e = bbox
    g = ox.truncate.truncate_graph_bbox(parent.graph, (w, s, e, n), truncate_by_edge=False)
    g = ox.truncate.largest_component(g, strongly=False)
    feats = parent.features.cx[w:e, s:n] if not parent.features.empty else parent.features
    region = Region(name, lat, lon, radius_m, nx.MultiDiGraph(g), feats,
                    {**{k: f"from area '{parent.name}': {v.split(' (')[0]}" for k, v in parent.sources.items()},
                     "network": f"cut from already-built area '{parent.name}' (no download)"})
    # clipped copies of the parent's point/feature layers
    for src, dst, clip in ((amenities_path(parent.name), amenities_path(name), cache.clip_geojson),
                           (config.DATA_DIR / f"stops_{parent.name}.geojson",
                            config.DATA_DIR / f"stops_{name}.geojson", cache.clip_geojson)):
        if src.exists():
            dst.write_text(json.dumps(clip(json.loads(src.read_text()), bbox)))
    for layer in ("crashes", "counters"):
        data = austin.load_cached(layer, parent.name)
        if data is not None:
            austin.cache(layer, name, cache.clip_points(data, bbox))
    return region


def _network(name, lat, lon, radius_m, opts, refresh):
    """(graph, scenic features, cycle-route ways, amenities or None, description)."""
    from cycleroutes.data import extract
    bbox = requested_bbox(lat, lon, radius_m)
    ex = extract.extract_for(*bbox)
    choice = opts["network"]
    if choice == "extract" and not ex:
        raise RuntimeError("No downloadable extract covers this area - use network 'overpass' or 'auto'")
    if choice == "extract" or (choice == "auto" and ex):
        path = extract.local_path(ex)
        stale = path.exists() and time.time() - path.stat().st_mtime > EXTRACT_MAX_AGE_S
        reuse = path.exists() and opts["prefer_cached"] and not refresh
        path = extract.fetch_extract(ex, refresh=not reuse and (stale or refresh or not path.exists()))
        graph, features, route_ways, amen = extract.build_from_extract(path, lat, lon, radius_m)
        age = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
        return graph, features, route_ways, amen, f"{ex['provider']} {ex['name']} extract, file from {age}"
    graph = osm_network.download_bike_network(lat, lon, radius_m)
    features = osm_network.download_scenic_features(lat, lon, radius_m)
    s, w, n, e = bbox
    route_ways = cycle_networks.fetch_cycle_route_ways(s, w, n, e)
    return graph, features, route_ways, None, "OpenStreetMap live (Overpass API)"


def build_region(name: str, lat: float, lon: float, radius_m: float, refresh: bool = False) -> Region:
    """Build an area, reusing downloaded data wherever the area's settings allow."""
    from cycleroutes.data.amenities import amenities_path
    from cycleroutes.data.sources.apply import apply_all   # local import: avoids a cycle
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    opts = settings.load(name)
    bbox = requested_bbox(lat, lon, radius_m)

    parent = find_covering_region(bbox, exclude=name) if opts["prefer_cached"] and not refresh else None
    if parent:
        logger.info("Cutting '%s' from already-built area '%s'", name, parent)
        region = _cut_from(load_region(parent), name, lat, lon, radius_m, bbox)
        save_region(region)
        return region

    graph, features, route_ways, amen, network_desc = _network(name, lat, lon, radius_m, opts, refresh)
    graph.graph.update(mode="bike", base_kmh=config.BASE_CYCLING_SPEED_KMH)
    region = Region(name, lat, lon, radius_m, graph, features)
    hit = cache.array_source("dem_copernicus", region.bbox, lambda b: elevation.fetch_elevation_grid(*b),
                             lambda g, p: cache.save_npz(p, data=g.data, meta=[g.west, g.north, g.res_x, g.res_y]),
                             elevation.ElevationGrid.load, refresh, opts["prefer_cached"])
    enrich.enrich(graph, features, hit.data, route_ways)
    if amen is not None:
        amenities_path(name).write_text(json.dumps(amen))
    else:
        amenities_path(name).unlink(missing_ok=True)    # fetched by apply_all
    apply_all(region, refresh=refresh)
    region.sources["network"] = network_desc
    save_region(region)
    return region


def save_region(region: Region) -> None:
    with open(region_path(region.name), "wb") as fh:
        pickle.dump(region, fh, protocol=pickle.HIGHEST_PROTOCOL)
    index = region_index()
    index[region.name] = {"bbox": list(region.bbox), "built": time.time(),
                          "network": region.sources.get("network", "")}
    _index_path().write_text(json.dumps(index, indent=1))
    logger.info("Region '%s' saved to %s", region.name, region_path(region.name))


def load_region(name: str) -> Region:
    path = region_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"Region '{name}' not built yet - run: python -m cycleroutes.cli build --name {name}")
    with open(path, "rb") as fh:
        region = pickle.load(fh)
    if not hasattr(region, "sources"):   # pickles from before open-data sources existed
        region.sources = {}
    return region
