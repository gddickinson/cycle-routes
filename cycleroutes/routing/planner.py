"""Trip builder: routes of a chosen length with the stops you want along the way.

    plan_trip(router, start, end=None (loop) | point, target_km=None,
              stops=[("cafe", 1), ("water", 2)], features=[...], profile, ctx)

1. Base: A->B, stretched towards target_km if asked (a detour via a point on an
   ellipse around A and B), or a loop of target_km from the start.
2. Stops: for each wanted category, real places near the base route (within a
   corridor), spread evenly along it (e.g. one café half-way, water every third).
3. The final route goes start -> stops (in along-route order) -> end / back to start.
Several variants are returned (different stretch directions / loops), best first.
"""

import math

from cycleroutes.routing import geo, rating
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.route import Route, overlap
from cycleroutes.routing.router import Router, RoutingError
from cycleroutes.routing.stops import along

STOP_TYPES = {      # key -> (label, stop-feature categories)
    "cafe": ("Café", {"cafe"}), "treat": ("Ice cream & treats", {"treat"}), "food": ("Food", {"food"}),
    "water": ("Drinking water", {"water"}), "toilets": ("Toilets", {"toilets"}),
    "park": ("Park", {"park"}), "sight": ("Sight / landmark", {"landmark"}),
    "bike_shop": ("Bike shop", {"bike_shop", "repair"}), "shop": ("Grocery / shop", {"shop"}),
    "swim": ("Swimming", {"swim"}), "bike_share": ("Bike share", {"bike_share"}),
}
CORRIDOR_M = {"bike": 600.0, "walk": 300.0}
NOT_A_PLACE = ("department", "office", "headquarters", "administration", "maintenance")


def _stretch_candidates(a, b, target_m: float, n: int = 6):
    """Via points on an ellipse with foci a, b whose length ~ target (straight-line)."""
    d = float(geo.haversine_m(*a, *b))
    semi = max(target_m / 2 / 1.25, d / 2 + 50)          # 1.25 = typical road detour
    reach = math.sqrt(max(semi ** 2 - (d / 2) ** 2, 0))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    heading = geo.bearing_deg(*a, *b)
    return [geo.destination(*mid, (heading + side * 90 + off) % 360, reach)
            for side in (-1, 1) for off in (-25, 0, 25)][:n]


def _bases(router: Router, start, end, target_km, profile, ctx) -> list[Route]:
    if end is None:
        if not target_km:
            raise RoutingError("A loop needs a distance")
        return [r for r, _ in generate_loops(router, start, target_km, profile, 3, ctx)]
    direct = router.route(start, end, profile, ctx=ctx)
    if not target_km or direct.length_m >= target_km * 1000 * 0.9:
        return [direct]
    out = []
    for via in _stretch_candidates(start, end, target_km * 1000):
        try:
            r = router.route(start, end, profile, via=[via], ctx=ctx)
        except RoutingError:
            continue
        if abs(r.length_m - target_km * 1000) <= target_km * 1000 * 0.35 and \
                all(overlap(r, o) < 0.7 for o in out):
            out.append(r)
    return out or [direct]


def choose_stops(base: Route, features: list[dict], wanted, corridor_m: float) -> list[dict]:
    """Real places near the route, spread evenly for each wanted (type, count)."""
    candidates = along(base, features, within_m=corridor_m)
    total_km = base.length_m / 1000
    chosen = []
    for key, count in wanted:
        cats = STOP_TYPES[key][1]
        pool = [c for c in candidates if c.get("category") in cats and (c.get("name") or key in ("water", "toilets"))
                and not any(w in str(c.get("name", "")).lower() for w in NOT_A_PLACE)]
        for i in range(count):
            target = total_km * (i + 1) / (count + 1)
            pick = min((c for c in pool if c not in chosen),
                       key=lambda c: abs(c["at_km"] - target) + c["off_route_m"] / 500, default=None)
            if pick:
                chosen.append(pick | {"stop_type": key, "stop_label": STOP_TYPES[key][0]})
    return sorted(chosen, key=lambda c: c["at_km"])


def plan_trip(router: Router, start, end=None, target_km=None, stops=(), features=(),
              profile="balanced", ctx=None, variants: int = 3) -> list[tuple[Route, list[dict]]]:
    wanted = [(k, max(1, min(int(n), 6))) for k, n in stops if k in STOP_TYPES]
    corridor = CORRIDOR_M.get(router.mode, 600.0)
    results = []
    for base in _bases(router, start, end, target_km, profile, ctx)[:variants]:
        picked = choose_stops(base, list(features), wanted, corridor) if wanted else []
        if picked:
            via = [(p["lat"], p["lon"]) for p in picked]
            try:
                route = router.route(start, end if end is not None else start, profile, via=via, ctx=ctx)
            except RoutingError:
                continue
        else:
            route = base
        route.kind = "loop" if end is None else "a_to_b"
        on_route = {(p["lat"], p["lon"]) for p in picked}
        placed = [s for s in along(route, [{"geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                                           "properties": {k: v for k, v in p.items() if k not in ("lat", "lon")}}
                                          for p in picked], within_m=150) if (s["lat"], s["lon"]) in on_route]
        route.meta["planned_stops"] = placed
        results.append((route, placed))
    if not results:
        raise RoutingError("Couldn't build a trip with those options - try fewer stops or another distance")
    missing = [STOP_TYPES[k][0] for k, _ in wanted if not any(s["stop_type"] == k for _, ss in results[:1] for s in ss)]
    for route, _ in results:
        route.meta["missing_stops"] = missing
    def score(rs):          # quality, minus a penalty for missing the requested length
        miss = abs(rs[0].length_m / 1000 - target_km) / target_km if target_km else 0.0
        return rating.rate(rs[0])["ratings"]["overall"] - 10 * miss
    results.sort(key=lambda rs: -score(rs))
    return results
