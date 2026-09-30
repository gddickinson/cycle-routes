"""Per-edge scores (0 = bad, 1 = good) and travel time.

Expects edges already enriched with: length, lts, scenic (0-1), route_rank (0-4),
ascent/descent (m). See cycleroutes.data.enrich.
"""

import math

from cycleroutes import config
from cycleroutes.scoring import lts as lts_mod
from cycleroutes.scoring import tags

LTS_SAFETY = {1: 1.0, 2: 0.75, 3: 0.35, 4: 0.05}

QUIET_BY_HIGHWAY = {
    "cycleway": 1.0, "path": 1.0, "track": 0.95, "footway": 0.95, "pedestrian": 0.95,
    "bridleway": 0.95, "steps": 0.9, "living_street": 0.95, "residential": 0.85,
    "service": 0.8, "unclassified": 0.65, "road": 0.6, "tertiary": 0.45,
    "secondary": 0.25, "primary": 0.1, "trunk": 0.0,
}

SURFACE_QUALITY = {
    "asphalt": 1.0, "paved": 1.0, "concrete": 0.95, "concrete:plates": 0.85,
    "paving_stones": 0.8, "chipseal": 0.8, "metal": 0.75, "wood": 0.7,
    "compacted": 0.65, "fine_gravel": 0.6, "sett": 0.55, "cobblestone": 0.4,
    "unhewn_cobblestone": 0.3, "gravel": 0.45, "pebblestone": 0.4, "unpaved": 0.35,
    "ground": 0.3, "dirt": 0.3, "earth": 0.3, "grass": 0.2, "sand": 0.1, "mud": 0.1,
}


def safety(edge: dict) -> float:
    score = LTS_SAFETY[edge["lts"]]
    # Recorded bike crashes on this segment (Vision Zero): each one costs a little,
    # serious/fatal ones more, capped so one bad block doesn't dominate.
    score -= min(0.35, 0.06 * edge.get("crashes", 0) + 0.12 * edge.get("crashes_severe", 0))
    if tags.first(edge, "lit") == "yes":
        score += 0.05
    if edge.get("route_rank", 0) > 0:
        score += 0.05  # signed routes usually have wayfinding and crossings
    return min(max(score, 0.0), 1.0)


def quietness(edge: dict) -> float:
    aadt = edge.get("aadt")
    if aadt:   # measured vehicles/day: 100 -> 1.0 ... 40,000 -> 0.0 (log scale)
        score = float(min(max(1 - (math.log10(aadt) - 2) / (math.log10(40000) - 2), 0.0), 1.0))
    else:
        score = QUIET_BY_HIGHWAY.get(tags.highway(edge), 0.6)
        if tags.lanes(edge) >= 4:
            score *= 0.6
    if tags.cycleway_kind(edge) == "track" or tags.highway(edge) in lts_mod.OFF_ROAD:
        score = max(score, 0.8)  # separated from whatever traffic is there
    db = edge.get("noise_db")
    if db:     # 42 dB or less -> calm, 72 dB -> loud
        score = 0.75 * score + 0.25 * min(max((72 - db) / 30, 0.0), 1.0)
    return score


def surface(edge: dict) -> float:
    known = [SURFACE_QUALITY[s] for s in tags.values(edge, "surface") if s in SURFACE_QUALITY]
    scale = tags.mtb_scale(edge)
    if scale is not None and scale >= 2:
        known.append(0.3)
    if known:
        return min(known)
    hw = tags.highway(edge)
    if hw in ("track", "bridleway"):
        return 0.45
    if hw in ("path", "footway"):
        return 0.7
    return 1.0


def fun(edge: dict) -> float:
    """Pleasantness: scenery, calm, being on a greenway/signed route, smoothness."""
    greenway = 1.0 if tags.highway(edge) in lts_mod.OFF_ROAD or tags.is_trail(edge) else 0.0
    route = min(edge.get("route_rank", 0), 2) / 2
    shade = edge.get("shade", 0.3)
    return (0.38 * edge.get("scenic", 0.0) + 0.22 * quietness(edge)
            + 0.15 * max(greenway, route) + 0.12 * surface(edge) + 0.13 * shade)


def speed_kmh(edge: dict) -> float:
    """Expected riding speed given gradient and surface."""
    length = max(edge["length"], 1.0)
    grade = (edge.get("ascent", 0.0) - edge.get("descent", 0.0)) / length
    base = config.BASE_CYCLING_SPEED_KMH * (0.6 + 0.4 * surface(edge))
    if tags.highway(edge) == "steps":
        return 3.0
    if tags.highway(edge) in ("footway", "pedestrian"):
        base = min(base, 12.0)  # shared with pedestrians
    scale = tags.mtb_scale(edge)
    if scale is not None and scale >= 1:   # technical singletrack: slower the harder it is
        base = min(base, max(16.0 - 3.0 * scale, 6.0))
    for service in tags.values(edge, "service"):
        if service in config.AWKWARD_SERVICE:
            base = min(base, config.AWKWARD_SERVICE[service][0])
    if grade > 0:
        return max(base / (1 + 12 * grade), 5.0)
    return min(base * (1 + 4 * -grade), config.MAX_DOWNHILL_SPEED_KMH)


def awkwardness(edge: dict) -> float:
    """Routing cost multiplier (>= 1) for parking aisles, driveways, etc."""
    return max([config.AWKWARD_SERVICE[s][1] for s in tags.values(edge, "service")
                if s in config.AWKWARD_SERVICE], default=1.0)


def travel_time_s(edge: dict) -> float:
    return edge["length"] / (speed_kmh(edge) / 3.6)
