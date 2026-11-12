"""Attach external data (scenery, elevation, signed routes) and scores to graph edges."""

import logging

import geopandas as gpd
import pandas as pd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString

from cycleroutes import config
from cycleroutes.data.elevation import ElevationGrid, climb_along
from cycleroutes.scoring import tags
# add_scores / add_crossings live in the GIS-free scoring.edge_attrs (the web demo uses them without
# geopandas/osmnx); re-exported here because callers use enrich.add_scores.
from cycleroutes.scoring.edge_attrs import ENHANCED_ATTRS, add_crossings, add_scores  # noqa: F401

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
    # Split the merged scenic area into its parts and index them, then intersect each
    # edge only with the parts near it (far faster than one huge multipolygon).
    area = feats_p.geometry.buffer(config.SCENIC_BUFFER_M).union_all()
    parts = gpd.GeoDataFrame(geometry=list(getattr(area, "geoms", [area])), crs=edges_p.crs)
    pairs = gpd.sjoin(edges_p[["geometry"]], parts, predicate="intersects", how="inner")
    inside = pd.Series(0.0, index=edges_p.index)
    for idx, right in pairs.groupby(level=[0, 1, 2])["index_right"]:
        edge = edges_p.geometry.loc[idx]
        inside.loc[idx] = sum(edge.intersection(parts.geometry.iloc[j]).length for j in right)
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


def enrich(graph: nx.MultiDiGraph, features: gpd.GeoDataFrame,
           grid: ElevationGrid, route_ways: dict) -> nx.MultiDiGraph:
    edges = _edge_geometries(graph)
    add_geometry(graph, edges)
    add_scenic_fraction(graph, edges, features)
    add_elevation(graph, grid)
    add_cycle_routes(graph, route_ways)
    add_scores(graph)
    return graph
