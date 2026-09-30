"""Cyclist amenities from OSM (adapted from pyNav's GeocodingService.search_nearby_pois).

Bike shops, repair stations, drinking water, toilets, parking and bike share,
fetched once per region and cached as GeoJSON next to the region graph.
"""

import json
import logging

from cycleroutes import config
from cycleroutes.data import overpass

logger = logging.getLogger(__name__)

# category -> (Overpass selector list, label, emoji used on the map)
CATEGORIES = {
    "bike_shop": (['shop="bicycle"'], "Bike shop", "🔧"),
    "repair": (['amenity="bicycle_repair_station"'], "Repair station", "🛠"),
    "water": (['amenity="drinking_water"'], "Drinking water", "💧"),
    "toilets": (['amenity="toilets"'], "Toilets", "🚻"),
    "bike_share": (['amenity="bicycle_rental"'], "Bike share", "🚲"),
    "parking": (['amenity="bicycle_parking"'], "Bike parking", "🅿"),
}
MAX_PARKING = 400  # parking racks are numerous; keep the layer light


def amenities_path(name: str):
    return config.DATA_DIR / f"amenities_{name}.geojson"


def _query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"({south},{west},{north},{east})"
    parts = [f"nwr[{sel}]{bbox};" for sels, _, _ in CATEGORIES.values() for sel in sels]
    return f"[out:json][timeout:90];({''.join(parts)});out center tags;"


def _category(tags: dict) -> str | None:
    if tags.get("shop") == "bicycle":
        return "bike_shop"
    return {"bicycle_repair_station": "repair", "drinking_water": "water", "toilets": "toilets",
            "bicycle_rental": "bike_share", "bicycle_parking": "parking"}.get(tags.get("amenity", ""))


def fetch_amenities(name: str, bbox: tuple[float, float, float, float]) -> dict:
    """Download, categorise and cache amenities for a region; returns GeoJSON."""
    data = overpass.with_fallback(lambda url: overpass.post_query(url, _query(*bbox), timeout=120))
    feats, parking = [], 0
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        cat = _category(tags)
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if not cat or lat is None:
            continue
        if cat == "parking":
            parking += 1
            if parking > MAX_PARKING:
                continue
        label = CATEGORIES[cat][1]
        props = {"category": cat, "label": label, "name": tags.get("name", ""),
                 "opening_hours": tags.get("opening_hours", ""),
                 "fee": tags.get("fee", ""), "capacity": tags.get("capacity", "")}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {k: v for k, v in props.items() if v}})
    geo = {"type": "FeatureCollection", "features": feats}
    amenities_path(name).write_text(json.dumps(geo))
    counts = {c: sum(f["properties"]["category"] == c for f in feats) for c in CATEGORIES}
    logger.info("Amenities: %s", counts)
    return geo


def load_amenities(name: str) -> dict:
    path = amenities_path(name)
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text())
