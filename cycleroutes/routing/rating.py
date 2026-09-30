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
    infra = signed = 0.0
    for d in route.edge_data():
        lts_share[d["lts"]] += d["length"]
        if tags.highway(d) == "cycleway" or tags.cycleway_kind(d) in ("lane", "track"):
            infra += d["length"]
        if d.get("route_rank", 0) > 0:
            signed += d["length"]
    lts_pct = {k: round(100 * v / max(length, 1), 1) for k, v in lts_share.items()}
    climb_per_km = ascent / km
    avg_kmh = (length / 1000) / max(time_s / 3600, 1e-6)

    if fastest_time_s:
        speed = 10 * fastest_time_s / max(time_s, 1)
    else:
        speed = (avg_kmh - 10) / (config.BASE_CYCLING_SPEED_KMH - 10) * 10

    ratings = {
        "safety": _clamp10(10 * _weighted(route, "safety")),
        "fun": _clamp10(10 * _weighted(route, "fun")),
        "traffic": _clamp10(10 * _weighted(route, "quiet")),
        "hills": _clamp10(10 - climb_per_km / 2.5),     # 10 = flat, 0 = 25 m/km
        "speed": _clamp10(speed),
        "surface": _clamp10(10 * _weighted(route, "surface_q")),
    }
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
    }
