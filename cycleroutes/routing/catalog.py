"""Pre-generated "suggested rides": rated loops from interesting hubs in a region.

Hubs are the region centre plus the largest named parks, so rides start
somewhere pleasant. Saved as JSON (edge lists + ratings) next to the region.
"""

import json
import logging

from cycleroutes import config
from cycleroutes.data.region import Region
from cycleroutes.routing.geo import NodeIndex
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.route import Route
from cycleroutes.routing.router import Router, RoutingError

logger = logging.getLogger(__name__)

DEFAULT_DISTANCES_KM = (8, 15, 25)
DEFAULT_PROFILES = ("scenic", "family", "balanced")
MAX_HUB_SNAP_M = 300


def catalog_path(name: str):
    return config.DATA_DIR / f"catalog_{name}.json"


def pick_hubs(region: Region, max_parks: int = 4) -> list[dict]:
    hubs = [{"name": "City centre", "lat": region.lat, "lon": region.lon}]
    feats = region.features
    if feats.empty or "leisure" not in feats.columns or "name" not in feats.columns:
        return hubs
    parks = feats[(feats["leisure"] == "park") & feats["name"].notna()].copy()
    if parks.empty:
        return hubs
    projected = parks.to_crs(parks.estimate_utm_crs())
    parks["area"] = projected.geometry.area
    index = NodeIndex(region.graph)
    for _, row in parks.sort_values("area", ascending=False).iterrows():
        c = row.geometry.representative_point()
        if index.nearest(c.y, c.x)[1] > MAX_HUB_SNAP_M:
            continue  # park interior far from streets, or outside the mapped area
        hubs.append({"name": str(row["name"]), "lat": c.y, "lon": c.x})
        if len(hubs) > max_parks:
            break
    return hubs


def build_catalog(region: Region, router: Router, distances=DEFAULT_DISTANCES_KM,
                  profiles=DEFAULT_PROFILES) -> list[dict]:
    rides = []
    for hub in pick_hubs(region):
        for km in distances:
            for profile in profiles:
                try:
                    loop, stats = generate_loops(router, (hub["lat"], hub["lon"]), km,
                                                 profile, count=1)[0]
                except RoutingError as exc:
                    logger.info("No %s km %s loop from %s: %s", km, profile, hub["name"], exc)
                    continue
                label = config.PROFILES[profile].label
                rides.append({
                    "title": f"{hub['name']}: {km} km {label.lower()} loop",
                    "hub": hub["name"], "profile": profile, "target_km": km,
                    "edges": [list(e) for e in loop.edges], "stats": stats,
                })
                logger.info("%s -> %.1f km, overall %.1f", rides[-1]["title"],
                            stats["distance_km"], stats["ratings"]["overall"])
    with open(catalog_path(region.name), "w") as fh:
        json.dump(rides, fh)
    return rides


def load_catalog(region: Region) -> list[tuple[Route, dict, str]]:
    """[(route, stats, title)] or [] if no catalog has been built."""
    path = catalog_path(region.name)
    if not path.exists():
        return []
    out = []
    for ride in json.loads(path.read_text()):
        edges = [tuple(e) for e in ride["edges"]]
        if not all(region.graph.has_edge(*e) for e in edges):
            continue  # region was rebuilt since the catalog was made
        route = Route(region.graph, edges, ride["profile"], kind="loop",
                      meta={"title": ride["title"], "hub": ride["hub"]})
        out.append((route, ride["stats"], ride["title"]))
    return out
