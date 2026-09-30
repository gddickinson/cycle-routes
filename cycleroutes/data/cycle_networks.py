"""Signed cycle routes (local/regional/national/international) from OSM relations.

Regional cycle maps are largely digitised in OpenStreetMap as `route=bicycle`
relations tagged with a `network` level (lcn, rcn, ncn, icn). Fetching them via
Overpass gives us the "official" cycle map layer for any region.
"""

import logging

from cycleroutes.data import overpass

logger = logging.getLogger(__name__)

NETWORK_RANK = {"icn": 4, "ncn": 3, "rcn": 2, "lcn": 1}


def fetch_cycle_route_ways(south: float, west: float, north: float, east: float) -> dict:
    """Map OSM way id -> {"rank": int, "names": [str]} for signed cycle routes."""
    query = f"""
    [out:json][timeout:60];
    relation["route"="bicycle"]({south},{west},{north},{east});
    out body;
    """
    try:
        data = overpass.with_fallback(lambda url: overpass.post_query(url, query, timeout=90))
    except RuntimeError as exc:
        logger.warning("Cycle route relations unavailable: %s", exc)
        return {}

    ways: dict[int, dict] = {}
    for rel in data.get("elements", []):
        tags = rel.get("tags", {})
        rank = NETWORK_RANK.get(tags.get("network", ""), 1)
        name = tags.get("name") or tags.get("ref") or "Cycle route"
        for member in rel.get("members", []):
            if member.get("type") != "way":
                continue
            entry = ways.setdefault(member["ref"], {"rank": 0, "names": []})
            entry["rank"] = max(entry["rank"], rank)
            if name not in entry["names"]:
                entry["names"].append(name)
    logger.info("Signed cycle routes cover %d ways", len(ways))
    return ways
