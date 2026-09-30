"""Download the rideable street network and scenic features from OpenStreetMap."""

import logging

import geopandas as gpd
import networkx as nx
import osmnx as ox

from cycleroutes import config
from cycleroutes.data import overpass

logger = logging.getLogger(__name__)


def _configure_osmnx() -> None:
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(config.DATA_DIR / "osmnx_http")
    ox.settings.log_console = False
    ox.settings.http_user_agent = config.USER_AGENT
    ox.settings.requests_timeout = 300
    ox.settings.overpass_rate_limit = False  # its slot-wait can hang on mirrors; we retry ourselves
    tags = list(ox.settings.useful_tags_way)
    ox.settings.useful_tags_way = tags + [t for t in config.EXTRA_WAY_TAGS if t not in tags]
    node_tags = list(ox.settings.useful_tags_node)
    if "highway" not in node_tags:
        ox.settings.useful_tags_node = node_tags + ["highway"]


def download_bike_network(lat: float, lon: float, radius_m: float) -> nx.MultiDiGraph:
    """Bike-legal street network within radius_m of (lat, lon), simplified."""
    _configure_osmnx()
    logger.info("Downloading OSM bike network (%.0f m around %.4f, %.4f)", radius_m, lat, lon)
    graph = overpass.with_fallback(lambda _url: ox.graph_from_point(
        (lat, lon), dist=radius_m, dist_type="bbox",
        network_type="bike", simplify=True, retain_all=False))
    logger.info("Network: %d nodes, %d edges", graph.number_of_nodes(), graph.number_of_edges())
    return graph


def download_scenic_features(lat: float, lon: float, radius_m: float) -> gpd.GeoDataFrame:
    """Parks, water, woods and viewpoints near the network (empty frame if none)."""
    _configure_osmnx()
    logger.info("Downloading scenic features")
    try:
        feats = overpass.with_fallback(lambda _url: ox.features_from_point(
            (lat, lon), tags=config.SCENIC_TAGS, dist=radius_m))
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    keep = [c for c in ["name", "leisure", "natural", "landuse", "waterway", "tourism"]
            if c in feats.columns]
    return feats[keep + ["geometry"]].reset_index()
