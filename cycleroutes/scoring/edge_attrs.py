"""Per-edge scores and junction flags computed from an edge's OSM tags and enrichment.

Pure graph code (networkx + the scoring modules, no geopandas/osmnx), so the full build
(data/enrich.py, data/sources/apply.py) and the web demo (cycleroutes/web/demo_area.py) share it.
"""

import logging

import networkx as nx
import numpy as np

from cycleroutes import config
from cycleroutes.routing.geo import bearing_deg
from cycleroutes.scoring import edge_scores, lts, tags

logger = logging.getLogger(__name__)

# attributes that come from sources other than OpenStreetMap
ENHANCED_ATTRS = ("city_lts", "city_facility", "aadt", "crashes", "crashes_severe", "noise_db", "shade")


def add_scores(graph: nx.MultiDiGraph) -> None:
    """Compute LTS, 0-1 scores and travel time for each edge."""
    signals = {n for n, d in graph.nodes(data=True) if d.get("highway") == "traffic_signals"}
    for _, v, data in graph.edges(data=True):
        (x0, y0), (x1, y1) = data["geometry"].coords[0], data["geometry"].coords[-1]
        data["bearing"] = round(bearing_deg(y0, x0, y1, x1), 1)
        data["trail"] = tags.is_trail(data)
        data["mtb_scale"] = tags.mtb_scale(data)
        data["bike_infra"] = tags.has_bike_infra(data)
        data["lts_osm"] = lts.classify(data)
        data["lts"] = lts.effective(data)
        data["safety"] = edge_scores.safety(data)
        data["quiet"] = edge_scores.quietness(data)
        data["surface_q"] = edge_scores.surface(data)
        data["fun"] = edge_scores.fun(data)
        data["time_s"] = edge_scores.travel_time_s(data)
        # OpenStreetMap-only variants, so a route can be planned without the extra data
        base = {k: v for k, v in data.items() if k not in ENHANCED_ATTRS}
        base["lts"] = data["lts_osm"]
        data["safety_osm"] = edge_scores.safety(base)
        data["quiet_osm"] = edge_scores.quietness(base)
        data["fun_osm"] = edge_scores.fun(base)
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
