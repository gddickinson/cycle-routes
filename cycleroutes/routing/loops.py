"""Generate round-trip rides of a target distance and rank them.

Method: for several compass bearings, place two waypoints so that start -> A ->
B -> start forms a roughly equilateral triangle sized for the target distance,
route each leg with the chosen profile, and penalise re-riding edges already
used earlier in the loop (avoids out-and-back "lollipops").
"""

import logging

from cycleroutes import config
from cycleroutes.routing import geo, rating
from cycleroutes.routing.route import Route, edges_from_nodes, overlap
from cycleroutes.routing.router import Router, RoutingError, make_cost, resolve_profile, shortest_nodes

logger = logging.getLogger(__name__)

PROFILE_RATING_KEY = {
    "safest": "safety", "family": "safety", "scenic": "fun", "flattest": "hills",
    "quiet": "traffic", "fastest": "speed", "shady": "shade", "trails": "fun", "mtb": "fun",
    "commute": "speed", "urban": "fun", "tourist": "fun", "hike": "fun", "green": "fun", "accessible": "safety",
}


def _loop_for_bearing(router: Router, start_node: int, bearing: float,
                      side_m: float, profile, ctx=None) -> Route:
    graph = router.graph
    slat, slon = graph.nodes[start_node]["y"], graph.nodes[start_node]["x"]
    a = router.index.nearest(*geo.destination(slat, slon, bearing, side_m))[0]
    b = router.index.nearest(*geo.destination(slat, slon, bearing + 60, side_m))[0]
    if len({start_node, a, b}) < 3:
        raise RoutingError("Waypoints collapsed onto the start")

    name, prof = resolve_profile(profile, router.mode)
    penalties: dict = {}
    edges = []
    for u, v in ((start_node, a), (a, b), (b, start_node)):
        cost = make_cost(prof, penalties, graph, ctx)
        nodes = shortest_nodes(graph, u, v, cost)
        leg = edges_from_nodes(graph, nodes, cost)
        edges.extend(leg)
        for x, y, _ in leg:
            penalties[(min(x, y), max(x, y))] = config.LOOP_REUSE_PENALTY
    return Route(graph, edges, name, kind="loop", ctx=ctx)


def _reuse_fraction(route: Route) -> float:
    seen, reused = set(), 0.0
    for (u, v, _), d in zip(route.edges, route.edge_data()):
        key = (min(u, v), max(u, v))
        if key in seen:
            reused += d["length"]
        seen.add(key)
    return reused / max(route.length_m, 1)


def generate_loops(router: Router, start: tuple[float, float], distance_km: float,
                   profile="scenic", count: int = 3, ctx=None) -> list[tuple[Route, dict]]:
    """Up to `count` distinct loops near distance_km, best first, with ratings."""
    start_node = router.snap(*start)
    side_m = distance_km * 1000 / (3 * config.LOOP_DETOUR_FACTOR)
    key = PROFILE_RATING_KEY.get(profile if isinstance(profile, str) else "", "overall")

    candidates = []
    for i in range(config.LOOP_BEARINGS):
        try:
            loop = _loop_for_bearing(router, start_node, i * 360 / config.LOOP_BEARINGS,
                                     side_m, profile, ctx)
        except RoutingError as exc:
            logger.debug("Bearing %d skipped: %s", i, exc)
            continue
        loop.meta["target_km"] = distance_km
        stats = rating.rate(loop)
        err = abs(stats["distance_km"] - distance_km) / distance_km
        reuse = _reuse_fraction(loop)
        stats["distance_error_pct"] = round(100 * err, 1)
        stats["reuse_pct"] = round(100 * reuse, 1)
        # Rank by the profile's headline rating, penalising a poor distance match
        # and riding the same street twice.
        score = stats["ratings"].get(key, stats["ratings"]["overall"]) + 0.5 * stats["ratings"]["overall"] - 10 * err - 5 * reuse
        candidates.append((score, err, loop, stats))

    candidates.sort(key=lambda c: -c[0])
    within = [c for c in candidates if c[1] <= config.LOOP_DISTANCE_TOLERANCE] or candidates
    chosen: list[tuple[Route, dict]] = []
    for _, _, loop, stats in within:
        if all(overlap(loop, other) < 0.5 for other, _ in chosen):
            chosen.append((loop, stats))
        if len(chosen) == count:
            break
    if not chosen:
        raise RoutingError("Could not build a loop here - try another start or distance")
    return chosen
