"""Per-edge scores for walking (0 = bad, 1 = good), stored under the same attribute
names as cycling (lts, safety, quiet, fun, surface_q, time_s) so the router, loops,
ratings, navigation and printing work unchanged on a walking network.

Pedestrian stress (1-4, stored as "lts"):
  1 paths, footways, pedestrian streets, calm residential streets
  2 streets with sidewalks and moderate traffic; quiet streets without sidewalks
  3 busy streets with sidewalks, or moderate streets without them
  4 fast, busy roads without sidewalks
"""

import math

from cycleroutes import config
from cycleroutes.scoring import edge_scores, tags

CAR_FREE = {"footway", "pedestrian", "path", "steps", "track", "living_street", "bridleway", "cycleway"}
PST_SAFETY = {1: 1.0, 2: 0.8, 3: 0.45, 4: 0.15}
SIDEWALK_YES = {"both", "left", "right", "yes", "separate"}
CITY_RATING_QUALITY = {1: 1.0, 2: 0.85, 3: 0.65, 4: 0.45, 5: 0.3}
HIKING_SLOW = {"hiking": 1.0, "mountain_hiking": 0.75, "demanding_mountain_hiking": 0.55,
               "alpine_hiking": 0.4, "demanding_alpine_hiking": 0.3, "difficult_alpine_hiking": 0.25}


def has_sidewalk(edge: dict) -> bool | None:
    """True / False if known (OSM tag or city inventory), None if nobody mapped it."""
    if edge.get("city_sidewalk") is not None:
        return bool(edge["city_sidewalk"])
    vals = []
    for key in ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right"):
        vals += tags.values(edge, key)
    if any(v in SIDEWALK_YES for v in vals):
        return True
    if vals and all(v in ("no", "none") for v in vals):
        return False
    return None


def pedestrian_stress(edge: dict) -> int:
    hw = tags.highway(edge)
    if hw in CAR_FREE:
        return 1
    speed, lanes = tags.speed_limit_kmh(edge), tags.lanes(edge)
    aadt = edge.get("aadt") or 0
    if hw in ("residential", "service", "unclassified") and speed <= 41 and aadt < 3000:
        return 1
    sidewalk = has_sidewalk(edge)
    if sidewalk or (sidewalk is None and hw in ("residential", "service")):
        return 2 if (aadt <= 15000 and speed <= 56 and lanes <= 4) else 3
    if speed <= 41 and aadt < 3000:
        return 2
    return 3 if speed <= 56 else 4


def safety(edge: dict) -> float:
    score = PST_SAFETY[edge["lts"]]
    score -= min(0.35, 0.05 * edge.get("ped_crashes", 0) + 0.12 * edge.get("ped_crashes_severe", 0))
    if tags.first(edge, "lit") == "yes":
        score += 0.05
    return min(max(score, 0.0), 1.0)


def surface(edge: dict) -> float:
    rating = edge.get("city_sidewalk_rating")
    if rating in CITY_RATING_QUALITY:
        return CITY_RATING_QUALITY[rating]
    s = edge_scores.surface(edge)
    return max(s, 0.6) if tags.highway(edge) in ("path", "track", "footway") else s   # dirt is fine on foot


def fun(edge: dict) -> float:
    """Pleasantness on foot: greenery, quiet, shade, street life, sights, car-free."""
    car_free = 1.0 if tags.highway(edge) in CAR_FREE else 0.0
    return (0.28 * edge.get("scenic", 0.0) + 0.2 * edge_scores.quietness(edge) + 0.15 * edge.get("shade", 0.3)
            + 0.14 * edge.get("lively", 0.0) + 0.13 * edge.get("sights", 0.0) + 0.1 * car_free)


def speed_kmh(edge: dict) -> float:
    """Tobler's hiking function (5 km/h on the flat), slower on steps and rough trails."""
    length = max(edge["length"], 1.0)
    grade = (edge.get("ascent", 0.0) - edge.get("descent", 0.0)) / length
    v = 6.0 * math.exp(-3.5 * abs(grade + 0.05)) * config.TOBLER_FLAT_KMH / (6.0 * math.exp(-0.175))
    if tags.highway(edge) == "steps":
        v = min(v, 2.5)
    return max(v * HIKING_SLOW.get(tags.first(edge, "sac_scale"), 1.0), 1.0)


def time_s(edge: dict) -> float:
    return edge["length"] / (speed_kmh(edge) / 3.6)


def accessible(edge: dict) -> bool:
    """Step-free and gentle enough for wheelchairs and strollers."""
    if tags.highway(edge) == "steps" or tags.first(edge, "wheelchair") == "no":
        return False
    if tags.first(edge, "sac_scale") not in ("", "hiking"):
        return False
    grade = max(edge.get("ascent", 0.0), edge.get("descent", 0.0)) / max(edge["length"], 1.0)
    return grade <= 0.08 and surface(edge) >= 0.6 and has_sidewalk(edge) is not False


def score_edge(edge: dict) -> None:
    """Compute and store every walking score on one edge."""
    edge["trail"] = tags.is_trail(edge) or tags.highway(edge) in ("path", "track")
    edge["sidewalk"] = has_sidewalk(edge)
    edge["lts_osm"] = edge["lts"] = pedestrian_stress(edge)
    edge["safety"] = safety(edge)
    edge["quiet"] = edge_scores.quietness(edge)
    edge["surface_q"] = surface(edge)
    edge["fun"] = fun(edge)
    edge["time_s"] = time_s(edge)
    edge["accessible"] = accessible(edge)
    edge["bike_infra"] = False
    edge["mtb_scale"] = None
    base = {k: v for k, v in edge.items() if k not in ("aadt", "noise_db", "shade", "ped_crashes",
                                                       "ped_crashes_severe", "city_sidewalk", "city_sidewalk_rating")}
    base["lts"] = pedestrian_stress(base)
    edge["safety_osm"], edge["quiet_osm"], edge["fun_osm"] = safety(base), edge_scores.quietness(base), fun(base)
