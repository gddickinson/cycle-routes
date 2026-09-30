"""Attach external data (scenery, elevation, signed routes) and scores to graph edges."""

import logging

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString

from cycleroutes import config
from cycleroutes.data.elevation import ElevationGrid, climb_along
from cycleroutes.scoring import edge_scores, lts, tags

logger = logging.getLogger(__name__)


def _edge_geometries(graph: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)
    return edges[["geometry", "length"]]


def add_geometry(graph: nx.MultiDiGraph, edges: gpd.GeoDataFrame) -> None:
    """Make sure every edge carries its (u->v oriented) LineString."""
    for (u, v, k), geom in edges.geometry.items():
        graph.edges[u, v, k]["geometry"] = geom


def add_scenic_fraction(graph: nx.MultiDiGraph, edges: gpd.GeoDataFrame,
                        features: gpd.GeoDataFrame) -> None:
    """Fraction (0-1) of each edge within SCENIC_BUFFER_M of green/blue space."""
    nx.set_edge_attributes(graph, 0.0, "scenic")
    if features.empty:
        return
    edges_p = ox.projection.project_gdf(edges)
    feats_p = features.to_crs(edges_p.crs)
    scenic_area = feats_p.geometry.buffer(config.SCENIC_BUFFER_M).union_all()
    inside = edges_p.geometry.intersection(scenic_area).length
    frac = (inside / edges_p.geometry.length.clip(lower=1)).clip(0, 1)
    for idx, value in frac.items():
        graph.edges[idx]["scenic"] = float(value)
    logger.info("Scenic: %.0f%% of edges touch green/blue space", 100 * (frac > 0.1).mean())


def add_elevation(graph: nx.MultiDiGraph, grid: ElevationGrid) -> None:
    """Node elevation plus per-edge ascent, descent and a sampled profile."""
    for node, data in graph.nodes(data=True):
        data["elevation"] = float(grid.sample([data["x"]], [data["y"]])[0])
    for u, v, data in graph.edges(data=True):
        geom: LineString = data["geometry"]
        length = data["length"]
        if tags.is_yes(data, "bridge") or tags.is_yes(data, "tunnel"):
            # DEM shows the valley/hill, not the deck: interpolate end-to-end.
            profile = np.array([graph.nodes[u]["elevation"], graph.nodes[v]["elevation"]])
        else:
            n = max(2, int(length // config.DEM_SAMPLE_SPACING_M) + 1)
            pts = [geom.interpolate(f, normalized=True) for f in np.linspace(0, 1, n)]
            profile = grid.sample(np.array([p.x for p in pts]), np.array([p.y for p in pts]))
        data["ascent"], data["descent"] = climb_along(profile, threshold=0.0)
        data["elev_profile"] = [round(float(z), 1) for z in profile]


def add_cycle_routes(graph: nx.MultiDiGraph, route_ways: dict) -> None:
    """route_rank (0 none, 1 local ... 4 international) and route names per edge."""
    for _, _, data in graph.edges(data=True):
        ids = data.get("osmid", [])
        ids = ids if isinstance(ids, list) else [ids]
        hits = [route_ways[i] for i in ids if i in route_ways]
        data["route_rank"] = max((h["rank"] for h in hits), default=0)
        data["route_names"] = sorted({n for h in hits for n in h["names"]})


def add_scores(graph: nx.MultiDiGraph) -> None:
    """Compute LTS, 0-1 scores and travel time for each edge."""
    signals = {n for n, d in graph.nodes(data=True) if d.get("highway") == "traffic_signals"}
    for _, v, data in graph.edges(data=True):
        data["lts"] = lts.classify(data)
        data["safety"] = edge_scores.safety(data)
        data["quiet"] = edge_scores.quietness(data)
        data["surface_q"] = edge_scores.surface(data)
        data["fun"] = edge_scores.fun(data)
        data["time_s"] = edge_scores.travel_time_s(data)
        data["awkward"] = edge_scores.awkwardness(data)
        if v in signals:
            data["time_s"] += config.TRAFFIC_SIGNAL_DELAY_S
    counts = np.bincount([d["lts"] for _, _, d in graph.edges(data=True)], minlength=5)[1:]
    logger.info("LTS distribution (1-4): %s", counts.tolist())


def enrich(graph: nx.MultiDiGraph, features: gpd.GeoDataFrame,
           grid: ElevationGrid, route_ways: dict) -> nx.MultiDiGraph:
    edges = _edge_geometries(graph)
    add_geometry(graph, edges)
    add_scenic_fraction(graph, edges, features)
    add_elevation(graph, grid)
    add_cycle_routes(graph, route_ways)
    add_scores(graph)
    return graph
