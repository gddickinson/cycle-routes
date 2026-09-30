"""Match a recorded GPS track to the street graph so a ride can be rated like a plan.

Simple and robust for a prototype: thin the track to points ~40 m apart, snap
each to the nearest graph node, and join consecutive nodes by the shortest
path. Good enough to know which streets (and so which stress levels, scenery,
climbs) a ride used; not a full HMM map-matcher.
"""

from cycleroutes.config import PROFILES
from cycleroutes.routing.geo import haversine_m
from cycleroutes.routing.route import Route, edges_from_nodes
from cycleroutes.routing.router import Router, RoutingError, make_cost, shortest_nodes

THIN_M = 40.0
MAX_SNAP_M = 60.0


def match_track(router: Router, points: list[dict]) -> tuple[Route | None, float]:
    """(matched route or None, fraction of thinned points that snapped to a street)."""
    thinned = []
    for p in points:
        if p.get("accuracy_m") and p["accuracy_m"] > 60:
            continue
        if not thinned or haversine_m(thinned[-1]["lat"], thinned[-1]["lon"], p["lat"], p["lon"]) >= THIN_M:
            thinned.append(p)
    if len(thinned) < 2:
        return None, 0.0

    nodes, snapped = [], 0
    for p in thinned:
        node, dist = router.index.nearest(p["lat"], p["lon"])
        if dist <= MAX_SNAP_M:
            snapped += 1
            if not nodes or nodes[-1] != node:
                nodes.append(node)
    coverage = snapped / len(thinned)
    if len(nodes) < 2:
        return None, coverage

    cost = make_cost(PROFILES["fastest"])
    path = [nodes[0]]
    for a, b in zip(nodes[:-1], nodes[1:]):
        try:
            leg = shortest_nodes(router.graph, a, b, cost)
        except RoutingError:
            continue
        path.extend(leg[1:])
    if len(path) < 2:
        return None, coverage
    route = Route(router.graph, edges_from_nodes(router.graph, path, cost), "ridden", kind="ride")
    return route, coverage
