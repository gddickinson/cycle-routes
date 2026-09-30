"""Geometry helpers that attach external data to graph edges."""

from collections import deque

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import Point, shape

from cycleroutes.scoring import tags

NON_ROAD = {"cycleway", "path", "footway", "pedestrian", "track", "bridleway", "steps"}


def edges_frame(graph: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    """One row per undirected street segment (u < v), projected to UTM metres."""
    rows, seen = [], set()
    for u, v, k, d in graph.edges(keys=True, data=True):
        key = (min(u, v), max(u, v), k)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"u": u, "v": v, "key": k, "hw": tags.highway(d), "name": tags.first(d, "name"),
                     "geometry": d["geometry"]})
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf.to_crs(gdf.estimate_utm_crs())


def set_both_directions(graph: nx.MultiDiGraph, u: int, v: int, key: int, **values) -> None:
    """Write attributes on u->v and, when present, the reverse v->u edge."""
    for a, b in ((u, v), (v, u)):
        if graph.has_edge(a, b):
            for k, d in graph[a][b].items():
                if k == key or len(graph[a][b]) == 1:
                    d.update(values)


def overlap_join(edges: gpd.GeoDataFrame, lines: gpd.GeoDataFrame, buffer_m: float = 10.0,
                 min_overlap: float = 0.5) -> dict:
    """Edge index -> row of `lines` covering the largest share of the edge (≥ min_overlap)."""
    lines = lines.to_crs(edges.crs).reset_index(drop=True)
    buffers = lines.copy()
    buffers["geometry"] = lines.geometry.buffer(buffer_m, cap_style="flat")
    pairs = gpd.sjoin(edges[["geometry"]], buffers, predicate="intersects", how="inner")
    best: dict = {}
    for eidx, row in pairs.iterrows():
        j = row["index_right"]
        length = max(edges.geometry[eidx].length, 1.0)
        share = edges.geometry[eidx].intersection(buffers.geometry[j]).length / length
        if share >= min_overlap and share > best.get(eidx, (None, 0))[1]:
            best[eidx] = (j, share)
    return {e: lines.iloc[j] for e, (j, _) in best.items()}


def nearest_edges(edges: gpd.GeoDataFrame, points: list[dict], max_m: float,
                  roads_only: bool = False) -> list[tuple[int, dict]]:
    """[(edge index, point)] snapping each point to its nearest edge within max_m."""
    if not points:
        return []
    cand = edges[~edges["hw"].isin(NON_ROAD)] if roads_only else edges
    pts = gpd.GeoDataFrame(points, geometry=[Point(p["lon"], p["lat"]) for p in points],
                           crs="EPSG:4326").to_crs(edges.crs)
    joined = gpd.sjoin_nearest(pts, cand[["geometry"]], max_distance=max_m, how="inner")
    joined = joined[~joined.index.duplicated()]
    return [(int(r["index_right"]), points[i]) for i, r in joined.iterrows()]


def propagate_by_name(graph: nx.MultiDiGraph, edges: gpd.GeoDataFrame, seeds: dict,
                      attr: str, max_m: float = 800.0) -> int:
    """Spread seed values {edge index: value} along the same-named street, up to max_m away.

    Edges nearer to a seed win; returns the number of edges assigned.
    """
    by_node: dict[int, list[int]] = {}
    for idx, row in edges.iterrows():
        if row["name"]:
            by_node.setdefault(row["u"], []).append(idx)
            by_node.setdefault(row["v"], []).append(idx)
    best: dict[int, tuple[float, float]] = {}      # edge idx -> (distance, value)
    for seed, value in seeds.items():
        name = edges.at[seed, "name"]
        queue = deque([(seed, 0.0)])
        while queue:
            idx, dist = queue.popleft()
            if dist > max_m or (idx in best and best[idx][0] <= dist):
                continue
            best[idx] = (dist, value)
            length = edges.geometry[idx].length
            for node in (edges.at[idx, "u"], edges.at[idx, "v"]):
                for nxt in by_node.get(node, []):
                    if nxt != idx and edges.at[nxt, "name"] == name:
                        queue.append((nxt, dist + length))
    for idx, (_, value) in best.items():
        r = edges.loc[idx]
        set_both_directions(graph, r["u"], r["v"], r["key"], **{attr: value})
    return len(best)


def sample_points(line, spacing_m: float, offsets_m=(0.0,)) -> tuple[np.ndarray, np.ndarray]:
    """(x, y) arrays of points along a projected line, optionally offset sideways."""
    n = max(2, int(line.length // spacing_m) + 1)
    dists = np.linspace(0, line.length, n)
    pts = np.array([line.interpolate(d).coords[0] for d in dists])
    if len(offsets_m) == 1 and offsets_m[0] == 0:
        return pts[:, 0], pts[:, 1]
    tangent = np.gradient(pts, axis=0)
    norm = np.hypot(tangent[:, 0], tangent[:, 1])[:, None]
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]]) / np.where(norm == 0, 1, norm)
    xs = np.concatenate([pts[:, 0] + o * normal[:, 0] for o in offsets_m])
    ys = np.concatenate([pts[:, 1] + o * normal[:, 1] for o in offsets_m])
    return xs, ys


def geojson_frame(geo: dict) -> gpd.GeoDataFrame:
    feats = [f for f in geo.get("features", []) if f.get("geometry")]
    return gpd.GeoDataFrame([f["properties"] for f in feats],
                            geometry=[shape(f["geometry"]) for f in feats], crs="EPSG:4326")
