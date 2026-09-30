"""Attach external data (scenery, elevation, signed routes) and scores to graph edges."""

import logging

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString

from cycleroutes import config
from cycleroutes.data.elevation import ElevationGrid, climb_along
from cycleroutes.routing.geo import bearing_deg
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
        (x0, y0), (x1, y1) = data["geometry"].coords[0], data["geometry"].coords[-1]
        data["bearing"] = round(bearing_deg(y0, x0, y1, x1), 1)
        data["lts_osm"] = lts.classify(data)
        data["lts"] = lts.effective(data)
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
    add_crossings(graph)


def add_crossings(graph: nx.MultiDiGraph) -> int:
    """Flag junctions where a low-stress street meets a high-stress road without signals.

    Crossing (or turning onto) a busy road there is the riskiest moment of a
    low-stress ride; the router penalises passing through these nodes.
    """
    n = 0
    und = graph.to_undirected(as_view=True)
    for node, nd in graph.nodes(data=True):
        busy, calm = set(), False
        for _, _, d in und.edges(node, data=True):
            if d.get("lts", 1) >= 3:
                busy.add(tags.first(d, "name") or "?")
            else:
                calm = True
        risky = (nd.get("highway") != "traffic_signals" and busy and calm and und.degree(node) >= 3)
        nd["risky_crossing"] = bool(risky)
        # Riding along the busy street itself (e.g. in its bike lane) is not a crossing;
        # the router only penalises arriving here from a differently named street.
        nd["busy_names"] = tuple(sorted(busy)) if risky else ()
        n += bool(risky)
    logger.info("Unsignalised low-to-high stress crossings: %d", n)
    return n


def enrich(graph: nx.MultiDiGraph, features: gpd.GeoDataFrame,
           grid: ElevationGrid, route_ways: dict) -> nx.MultiDiGraph:
    edges = _edge_geometries(graph)
    add_geometry(graph, edges)
    add_scenic_fraction(graph, edges, features)
    add_elevation(graph, grid)
    add_cycle_routes(graph, route_ways)
    add_scores(graph)
    return graph
