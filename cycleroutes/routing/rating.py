"""Rate a route 0-10 on each thing a rider might care about."""

import numpy as np

from cycleroutes import config
from cycleroutes.routing.route import Route
from cycleroutes.scoring import tags

MIN_GRADE_RUN_M = 60.0  # grade is measured over at least this distance (DEM noise)


def _weighted(route: Route, key: str) -> float:
    lengths = np.array([d["length"] for d in route.edge_data()])
    vals = np.array([d[key] for d in route.edge_data()], dtype=float)
    return float((lengths * vals).sum() / max(lengths.sum(), 1))


def _weighted_default(route: Route, key: str, default: float) -> float:
    lengths = np.array([d["length"] for d in route.edge_data()])
    vals = np.array([d.get(key, default) for d in route.edge_data()], dtype=float)
    return float((lengths * vals).sum() / max(lengths.sum(), 1))


def _walk_stats(route: Route, length: float) -> dict:
    """Extra facts for walks: sidewalks, step-free share, street life, sights, steps."""
    def share(pred):
        return round(100 * sum(d["length"] for d in route.edge_data() if pred(d)) / max(length, 1), 1)
    steps = sum(1 for d in route.edge_data() if tags.highway(d) == "steps")
    return {"mode": "walk", "sidewalk_pct": share(lambda d: d.get("sidewalk") or tags.highway(d) in
                                                   ("footway", "pedestrian", "path", "living_street")),
            "no_sidewalk_pct": share(lambda d: d.get("sidewalk") is False),
            "accessible_pct": share(lambda d: d.get("accessible")), "lively_pct": share(lambda d: d.get("lively", 0) >= 0.3),
            "sights_pct": share(lambda d: d.get("sights")), "steps": steps,
            "ped_crashes": sum(d.get("ped_crashes", 0) for d in route.edge_data())}


def max_grade_pct(profile: list[tuple[float, float]]) -> float:
    """Steepest sustained climb (%) over runs of >= MIN_GRADE_RUN_M."""
    if len(profile) < 2:
        return 0.0
    dist = np.array([p[0] for p in profile])
    elev = np.array([p[1] for p in profile])
    best, j = 0.0, 0
    for i in range(len(dist)):
        while j < len(dist) and dist[j] - dist[i] < MIN_GRADE_RUN_M:
            j += 1
        if j >= len(dist):
            break
        best = max(best, (elev[j] - elev[i]) / (dist[j] - dist[i]))
    return round(100 * best, 1)


def hill_label(climb_per_km: float) -> str:
    if climb_per_km < 5:
        return "Flat"
    if climb_per_km < 12:
        return "Rolling"
    if climb_per_km < 25:
        return "Hilly"
    return "Very hilly"


def _clamp10(x: float) -> float:
    return round(float(min(max(x, 0.0), 10.0)), 1)


def rate(route: Route, fastest_time_s: float | None = None) -> dict:
    """Summary stats and 0-10 ratings (10 = best) for a route.

    fastest_time_s: if known (A-to-B), speed is rated relative to the fastest
    option; otherwise from average speed.
    """
    length = route.length_m
    time_s = route.time_s
    km = max(length / 1000, 0.01)
    ascent = sum(d.get("ascent", 0.0) for d in route.edge_data())
    descent = sum(d.get("descent", 0.0) for d in route.edge_data())
    lts_share = {lvl: 0.0 for lvl in (1, 2, 3, 4)}
    infra = signed = trail = avoided = 0.0
    ctx = route.ctx
    ctx_avoid = ctx.avoided if ctx is not None and getattr(ctx, "avoid", None) else None
    for d in route.edge_data():
        lts_share[d["lts"]] += d["length"]
        if d.get("bike_infra", tags.has_bike_infra(d)):
            infra += d["length"]
        if d.get("trail"):
            trail += d["length"]
        if ctx_avoid is not None and ctx_avoid(d):
            avoided += d["length"]
        if d.get("route_rank", 0) > 0:
            signed += d["length"]
    lts_pct = {k: round(100 * v / max(length, 1), 1) for k, v in lts_share.items()}
    climb_per_km = ascent / km
    avg_kmh = (length / 1000) / max(time_s / 3600, 1e-6)

    base_kmh = route.graph.graph.get("base_kmh", config.BASE_CYCLING_SPEED_KMH)
    if fastest_time_s:
        speed = 10 * fastest_time_s / max(time_s, 1)
    else:
        speed = (avg_kmh - base_kmh / 2) / (base_kmh / 2) * 10

    crashes = sum(d.get("crashes", 0) for d in route.edge_data())
    severe = sum(d.get("crashes_severe", 0) for d in route.edge_data())
    nodes = route.graph.nodes
    crossings = sum(1 for (u, v, _), d in zip(route.edges, route.edge_data())
                    if nodes[v].get("risky_crossing") and d["lts"] <= 2
                    and (tags.first(d, "name") or "?") not in nodes[v].get("busy_names", ()))
    measured = sum(d["length"] for d in route.edge_data() if d.get("aadt"))
    busiest = max((d.get("aadt", 0) for d in route.edge_data()), default=0)
    has_noise = any("noise_db" in d for d in route.edge_data())
    has_shade = any("shade" in d for d in route.edge_data())
    # each unsignalised busy crossing on a low-stress ride knocks safety down a little
    crossing_penalty = min(2.0, 0.25 * crossings)

    ratings = {
        "safety": _clamp10(10 * _weighted(route, "safety") - crossing_penalty),
        "fun": _clamp10(10 * _weighted(route, "fun")),
        "traffic": _clamp10(10 * _weighted(route, "quiet")),
        "hills": _clamp10(10 - climb_per_km / 2.5),     # 10 = flat, 0 = 25 m/km
        "speed": _clamp10(speed),
        "surface": _clamp10(10 * _weighted(route, "surface_q")),
        "shade": _clamp10(10 * _weighted_default(route, "shade", 0.3)) if has_shade else None,
    }
    if ratings["shade"] is None:
        del ratings["shade"]
    ratings["overall"] = _clamp10(
        0.3 * ratings["safety"] + 0.2 * ratings["fun"] + 0.15 * ratings["traffic"]
        + 0.1 * ratings["hills"] + 0.15 * ratings["speed"] + 0.1 * ratings["surface"])

    route_names = sorted({n for d in route.edge_data() for n in d.get("route_names", [])})
    return {
        "distance_km": round(length / 1000, 2),
        "duration_min": round(time_s / 60, 1),
        "avg_speed_kmh": round(avg_kmh, 1),
        "ascent_m": round(ascent),
        "descent_m": round(descent),
        "max_grade_pct": max_grade_pct(route.elevation_profile()),
        "hill_label": hill_label(climb_per_km),
        "lts_pct": lts_pct,
        "bike_infra_pct": round(100 * infra / max(length, 1), 1),
        "signed_route_pct": round(100 * signed / max(length, 1), 1),
        "signed_routes": route_names[:6],
        "scenic_pct": round(100 * _weighted(route, "scenic"), 1),
        "ratings": ratings,
        "trail_pct": round(100 * trail / max(length, 1), 1),
        "max_mtb_scale": max((d["mtb_scale"] for d in route.edge_data() if d.get("mtb_scale") is not None),
                             default=None),
        "avoided_km": round(avoided / 1000, 2) if ctx_avoid else None,
        **(_walk_stats(route, length) if route.graph.graph.get("mode") == "walk" else {}),
        "crashes": crashes, "crashes_severe": severe, "risky_crossings": crossings,
        "measured_traffic_pct": round(100 * measured / max(length, 1), 1),
        "busiest_aadt": int(busiest) or None,
        "avg_noise_db": round(_weighted_default(route, "noise_db", 45.0), 1) if has_noise else None,
        "notice": route.meta.get("notice"),
        "context": route.ctx.describe() if route.ctx is not None else [],
    }
