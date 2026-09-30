"""Live bike-share availability from a GBFS feed (CapMetro Bikeshare for Austin)."""

import logging
import time

import requests

from cycleroutes import config

logger = logging.getLogger(__name__)
CACHE_S = 60
_cache: dict = {}


def _get(url: str) -> dict:
    return requests.get(url, timeout=15, headers={"User-Agent": config.USER_AGENT}).json()


def _feeds(gbfs_url: str) -> dict:
    data = _get(gbfs_url)["data"]
    feeds = data.get("feeds") or next(iter(data.values()))["feeds"]   # v3 flat, v2 per-language
    return {f["name"]: f["url"] for f in feeds}


def stations(gbfs_url: str = config.GBFS_URL) -> dict:
    """GeoJSON of stations with bikes / e-bikes / docks available (cached 60 s)."""
    hit = _cache.get(gbfs_url)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        feeds = _feeds(gbfs_url)
        info = _get(feeds["station_information"])["data"]["stations"]
        electric = set()
        if "vehicle_types" in feeds:
            electric = {v["vehicle_type_id"] for v in _get(feeds["vehicle_types"])["data"]["vehicle_types"]
                        if "electric" in v.get("propulsion_type", "")}
        status = {s["station_id"]: s for s in _get(feeds["station_status"])["data"]["stations"]}
    except (requests.RequestException, KeyError, ValueError) as exc:
        logger.warning("Bike share feed unavailable: %s", exc)
        return {"type": "FeatureCollection", "features": []}
    feats = []
    for s in info:
        st = status.get(s["station_id"], {})
        name = s.get("name")
        if isinstance(name, list):          # GBFS v3 localised names
            name = name[0].get("text") if name else ""
        ebikes = sum(v.get("count", 0) for v in st.get("vehicle_types_available", [])
                     if v.get("vehicle_type_id") in electric)
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                      "properties": {"name": name, "bikes": st.get("num_vehicles_available", st.get("num_bikes_available", 0)),
                                     "ebikes": ebikes, "docks": st.get("num_docks_available", 0),
                                     "renting": bool(st.get("is_renting", True))}})
    geo = {"type": "FeatureCollection", "features": feats, "fetched": time.time()}
    _cache[gbfs_url] = (time.time(), geo)
    return geo
