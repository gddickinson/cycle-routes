"""Sightseeing tours: visit a handful of well-rated sights near a start point.

1. candidates: named landmarks, museums, viewpoints and parks (Overture places) within
   reach of the start, scored by type and data confidence, spread out (≥ 150 m apart);
2. order: nearest-neighbour from the start, improved with 2-opt (straight-line distance);
3. route: the chosen profile (default Sightseeing) through the stops, back to the start
   for a loop; if it runs long, the weakest stop is dropped and the tour re-planned.
"""

from cycleroutes.routing import geo
from cycleroutes.routing.route import Route
from cycleroutes.routing.router import Router, RoutingError

KIND_WEIGHT = {"landmark": 1.0, "park": 0.7, "swim": 0.5}
MIN_SPACING_M = 150.0


def _dist(a, b) -> float:
    return float(geo.haversine_m(a[0], a[1], b[0], b[1]))


def pick_sights(features: list[dict], start, radius_m: float, n: int) -> list[dict]:
    cands = []
    for f in features:
        p = f["properties"]
        w = KIND_WEIGHT.get(p.get("category"))
        if not w or not p.get("name"):
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        d = _dist(start, (lat, lon))
        if d > radius_m:
            continue
        score = w * (0.5 + 0.5 * p.get("confidence", 0.6)) * (1.2 - 0.4 * d / radius_m)
        cands.append({"name": p["name"], "kind": p.get("kind") or p.get("category"), "lat": lat, "lon": lon,
                      "score": round(score, 3)})
    chosen, names = [], set()
    for c in sorted(cands, key=lambda c: -c["score"]):
        if c["name"].lower() in names or any(_dist((c["lat"], c["lon"]), (o["lat"], o["lon"])) < MIN_SPACING_M
                                             for o in chosen):
            continue
        chosen.append(c)
        names.add(c["name"].lower())
        if len(chosen) == n:
            break
    return chosen


def order_stops(start, stops: list[dict], loop: bool) -> list[dict]:
    """Nearest neighbour from the start, then 2-opt on straight-line distance."""
    rest, order, here = list(stops), [], start
    while rest:
        nxt = min(rest, key=lambda s: _dist(here, (s["lat"], s["lon"])))
        order.append(nxt)
        rest.remove(nxt)
        here = (nxt["lat"], nxt["lon"])

    def length(seq):
        pts = [start] + [(s["lat"], s["lon"]) for s in seq] + ([start] if loop else [])
        return sum(_dist(a, b) for a, b in zip(pts[:-1], pts[1:]))
    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if length(cand) + 1 < length(order):
                    order, improved = cand, True
    return order


def generate_tour(router: Router, start, features: list[dict], max_km: float = 5.0, n_stops: int = 6,
                  profile="tourist", loop: bool = True, ctx=None) -> tuple[Route, list[dict]]:
    radius = max_km * 1000 / (2.6 if loop else 1.6)
    stops = pick_sights(features, start, radius, n_stops)
    if not stops:
        raise RoutingError("No named sights within reach - try a longer tour or another start")
    while stops:
        ordered = order_stops(start, stops, loop)
        via = [(s["lat"], s["lon"]) for s in ordered]
        end = start if loop else via.pop()
        route = router.route(start, end, profile, via=via or None, ctx=ctx) if (via or end != start) else None
        if route is None:
            raise RoutingError("Tour collapsed onto the start point")
        if route.length_m <= max_km * 1000 * 1.3 or len(stops) == 1:
            route.kind = "loop" if loop else "a_to_b"
            route.meta.update(title=f"Sightseeing tour: {len(ordered)} stops", tour=ordered)
            return route, ordered
        stops.remove(min(stops, key=lambda s: s["score"]))     # too long: drop the weakest sight
    raise RoutingError("Could not fit a tour into that distance")

