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
