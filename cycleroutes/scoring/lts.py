"""Level of Traffic Stress (LTS 1-4) from OSM tags.

A simplified version of the Mekuria/Furth/Nixon (2012) method as commonly applied
to OSM data (e.g. BikeOttawa's stressmodel):
  LTS 1 - separated paths, calm residential streets (suitable for children)
  LTS 2 - most adults comfortable (painted lanes on slower roads, quiet streets)
  LTS 3 - confident cyclists (lanes on faster roads, busier mixed traffic)
  LTS 4 - strong & fearless only (fast, multi-lane mixed traffic)
"""

from cycleroutes.scoring import tags

OFF_ROAD = {"cycleway", "path", "track", "bridleway", "footway", "pedestrian"}
CALM_STREETS = {"residential", "living_street", "service"}


def classify(edge: dict) -> int:
    hw = tags.highway(edge)
    if hw in OFF_ROAD:
        return 1
    if hw == "steps":
        return 2  # walk-your-bike; low stress, just slow
    kind = tags.cycleway_kind(edge)
    if kind == "track":
        return 1

    speed = tags.speed_limit_kmh(edge)
    n_lanes = tags.lanes(edge)

    if kind == "lane":
        if speed <= 50 and n_lanes <= 2:
            return 2
        if speed <= 65 and n_lanes <= 4:
            return 3
        return 4

    # Mixed traffic
    if hw == "living_street" or (hw in CALM_STREETS and speed <= 40 and n_lanes <= 2):
        return 1
    if speed <= 40 and n_lanes <= 2:
        return 2
    if speed <= 50 and n_lanes <= 2 and hw not in ("primary", "trunk"):
        return 3
    return 4


def with_measured_traffic(osm_lts: int, edge: dict) -> int:
    """Adjust an OSM-derived LTS with a measured traffic volume (AADT), when known.

    Furth's tables: mixed traffic on streets with > ~8,000 vehicles/day is at least
    LTS 3, and > ~20,000/day is LTS 4; painted lanes help only up to LTS 3.
    """
    aadt = edge.get("aadt")
    if not aadt or tags.highway(edge) in OFF_ROAD or tags.cycleway_kind(edge) == "track":
        return osm_lts
    lane = tags.cycleway_kind(edge) == "lane"
    if aadt >= 20000:
        return max(osm_lts, 3 if lane else 4)
    if aadt >= 8000:
        return max(osm_lts, 2 if lane else 3)
    if aadt < 1500 and osm_lts == 2 and not lane:
        return 1
    return osm_lts


def effective(edge: dict) -> int:
    """Final LTS: OSM tags, adjusted by measured traffic, blended with the city's own
    comfort rating when available (ties round towards the more stressful level)."""
    level = with_measured_traffic(classify(edge), edge)
    city = edge.get("city_lts")
    if city:
        level = int((level + city) / 2 + 0.5)
    return level
