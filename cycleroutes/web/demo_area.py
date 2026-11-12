"""The web demo area: a small scored street network stored as compact JSON in cycleroutes/web/demo/.

The JSON (written by scripts/make_demo_area.py from a region built with `cycleroutes build`) keeps each edge's raw
OpenStreetMap tags plus the enrichment that needs GIS data (length, scenic share, climb, signed routes, geometry,
elevation profile). load_graph() rebuilds a networkx graph from it and scores it with the package's own
scoring.edge_attrs.add_scores, so the real Router, rating and loop code run on it with no download and no GIS stack.
The browser does the same in static/demo_graph.js.
"""
import json
from functools import lru_cache
from pathlib import Path

import networkx as nx
from shapely.geometry import LineString

from cycleroutes import config
from cycleroutes.scoring.edge_attrs import add_scores

DEMO_DIR = Path(__file__).resolve().parent / "demo"
DEMO_AREA = "prospect_park"

# Column order of demo["edges"] rows (shared with static/demo_graph.js and scripts/make_demo_area.py).
EDGE_COLUMNS = ("u", "v", "key", "tagset", "length", "scenic", "ascent", "descent", "route_rank", "geom", "names")


def demo_path(name: str = DEMO_AREA) -> Path:
    return DEMO_DIR / f"{name}.json"


@lru_cache(maxsize=2)
def load_demo(name: str = DEMO_AREA) -> dict:
    return json.loads(demo_path(name).read_text())


def _pairs(flat: list[float]) -> list[tuple[float, float]]:
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]


def graph_from_demo(demo: dict) -> nx.MultiDiGraph:
    """Scored MultiDiGraph (nodes 0..n-1, in file order) from the demo JSON."""
    g = nx.MultiDiGraph(crs="EPSG:4326", mode="bike", base_kmh=config.BASE_CYCLING_SPEED_KMH)
    signals = set(demo["nodes"]["signals"])
    for i, (lat, lon) in enumerate(zip(demo["nodes"]["lat"], demo["nodes"]["lon"])):
        g.add_node(i, y=lat, x=lon, **({"highway": "traffic_signals"} if i in signals else {}))
    geoms = [_pairs(flat) for flat in demo["geoms"]]
    for row in demo["edges"]:
        r = dict(zip(EDGE_COLUMNS, row))
        fwd = r["geom"] >= 0
        idx = r["geom"] if fwd else -r["geom"] - 1
        coords = geoms[idx] if fwd else geoms[idx][::-1]
        prof = demo["elev"][idx] if fwd else demo["elev"][idx][::-1]
        names = demo["route_names"][r["names"]] if r["names"] >= 0 else []
        g.add_edge(r["u"], r["v"], key=r["key"], **demo["tagsets"][r["tagset"]], length=r["length"],
                   scenic=r["scenic"], ascent=r["ascent"], descent=r["descent"], route_rank=r["route_rank"],
                   route_names=list(names), geometry=LineString(coords), elev_profile=list(prof))
    add_scores(g)
    return g


@lru_cache(maxsize=2)
def load_graph(name: str = DEMO_AREA) -> nx.MultiDiGraph:
    return graph_from_demo(load_demo(name))


def summary(name: str = DEMO_AREA) -> dict:
    """Counts for the home page: nodes, directed edges, network km (each street once) and km per LTS level."""
    g = load_graph(name)
    seen, km, trail, lts_km = set(), 0.0, 0.0, {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    for u, v, k, d in g.edges(keys=True, data=True):
        key = (min(u, v), max(u, v), k)
        if key in seen:
            continue
        seen.add(key)
        km += d["length"] / 1000
        lts_km[d["lts"]] += d["length"] / 1000
        trail += d["length"] / 1000 if d["trail"] else 0.0
    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(), "network_km": round(km, 1),
            "lts_km": {str(k): round(v, 1) for k, v in lts_km.items()},
            "trail_km": round(trail, 1),
            "risky_crossings": sum(1 for _, d in g.nodes(data=True) if d.get("risky_crossing"))}
