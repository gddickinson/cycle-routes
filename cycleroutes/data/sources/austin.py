"""City of Austin open data (Socrata): crashes, bike facilities + comfort, counters, work zones.

Applies only to regions inside config.AUSTIN_BBOX. All endpoints are public, no key.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from cycleroutes import config

logger = logging.getLogger(__name__)
PAGE = 5000

# City "bike_level_of_comfort" codes -> equivalent Level of Traffic Stress.
# (HP/HU high comfort paved/unpaved trail, H high, M medium, L low, EL/SS very low,
#  RT rough trail.) Inferred from the facilities they label; the dataset has no codebook.
COMFORT_TO_LTS = {"HP": 1, "HU": 1, "H": 1, "RT": 1, "M": 2, "L": 3, "EL": 4, "SS": 4}


def covers(south: float, west: float, north: float, east: float) -> bool:
    s, w, n, e = config.AUSTIN_BBOX
    return s <= south and north <= n and w <= west and east <= e


def _socrata(dataset: str, params: dict) -> list[dict]:
    rows, offset = [], 0
    while True:
        page = dict(params, **{"$limit": PAGE, "$offset": offset})
        resp = requests.get(f"{config.AUSTIN_SOCRATA}/{dataset}.json", params=page, timeout=120,
                            headers={"User-Agent": config.USER_AGENT})
        resp.raise_for_status()
        batch = resp.json()
        rows += batch
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def _in_box(lat: float, lon: float, bbox) -> bool:
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


def fetch_bike_crashes(bbox, mode: str = "bicycle") -> list[dict]:
    """Crashes involving a bicycle (or mode="pedestrian") in the last CRASH_YEARS years."""
    since = (datetime.now() - timedelta(days=365 * config.CRASH_YEARS)).strftime("%Y-%m-%dT00:00:00")
    s, w, n, e = bbox
    unit = "Pedestrian" if mode == "pedestrian" else "Bicycle"
    rows = _socrata(config.AUSTIN_CRASHES, {
        "$select": f"latitude,longitude,crash_timestamp_ct,crash_sev_id,units_involved,"
                   f"{mode}_death_count,{mode}_serious_injury_count,address_display",
        "$where": f"units_involved like '%{unit}%' AND crash_timestamp > '{since}' AND "
                  f"latitude between {s} and {n} AND longitude between {w} and {e}"})
    out = []
    for r in rows:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"lat": lat, "lon": lon, "date": r.get("crash_timestamp_ct", "")[:10],
                    "severe": int(r.get(f"{mode}_death_count") or 0) + int(r.get(f"{mode}_serious_injury_count") or 0) > 0,
                    "fatal": int(r.get(f"{mode}_death_count") or 0) > 0,
                    "where": r.get("address_display", "")})
    logger.info("Austin %s crashes: %d (%d severe)", mode, len(out), sum(c["severe"] for c in out))
    return out


def fetch_ped_crashes(bbox) -> list[dict]:
    return fetch_bike_crashes(bbox, mode="pedestrian")


SIDEWALK_EXISTS = {"EXISTING_SIDEWALK", "SHARED_USE_PATH", "SHARED_STREET", "PROTECTED_STREET_PATH"}
SIDEWALK_MISSING = {"POTENTIAL_SIDEWALK", "PLANNED_SIDEWALK"}


def fetch_sidewalks(bbox) -> dict:
    """City sidewalk inventory: existing sidewalks (with condition 1 good..5 poor) and missing ones."""
    s, w, n, e = bbox
    feats, offset = [], 0
    while True:
        resp = requests.get(f"{config.AUSTIN_SOCRATA}/{config.AUSTIN_SIDEWALKS}.geojson", timeout=180,
                            headers={"User-Agent": config.USER_AGENT}, params={
                                "$select": "the_geom,pedestrian_facility_type,rating_overall,width_sidewalk",
                                "$where": f"within_box(the_geom, {n}, {w}, {s}, {e}) AND "
                                          "pedestrian_facility_type != 'DRIVEWAY'",
                                "$limit": 20000, "$offset": offset})
        resp.raise_for_status()
        page = resp.json().get("features", [])
        for f in page:
            p, g = f.get("properties") or {}, f.get("geometry")
            kind = p.get("pedestrian_facility_type")
            if not g or kind not in SIDEWALK_EXISTS | SIDEWALK_MISSING:
                continue
            rating = p.get("rating_overall")
            feats.append({"type": "Feature", "geometry": g, "properties": {
                "exists": kind in SIDEWALK_EXISTS, "kind": kind,
                "rating": int(rating) if rating and str(rating).isdigit() else None}})
        if len(page) < 20000:
            break
        offset += 20000
    logger.info("Austin sidewalk segments: %d (%d missing)", len(feats), sum(not f["properties"]["exists"] for f in feats))
    return {"type": "FeatureCollection", "features": feats}


def fetch_bike_facilities(bbox) -> dict:
    """City bike-facility lines with 'comfort' (LTS-equivalent) and facility type, as GeoJSON."""
    s, w, n, e = bbox
    resp = requests.get(f"{config.AUSTIN_SOCRATA}/{config.AUSTIN_BIKE_FACILITIES}.geojson", timeout=180,
                        params={"$where": f"within_box(the_geom, {n}, {w}, {s}, {e})", "$limit": 50000},
                        headers={"User-Agent": config.USER_AGENT})
    resp.raise_for_status()
    feats = []
    for f in resp.json().get("features", []):
        p, g = f.get("properties") or {}, f.get("geometry")
        lts = COMFORT_TO_LTS.get((p.get("bike_level_of_comfort") or "").upper())
        if not g or lts is None:
            continue
        feats.append({"type": "Feature", "geometry": g,
                      "properties": {"city_lts": lts, "facility": p.get("bicycle_facility") or "",
                                     "comfort": p.get("bike_level_of_comfort"), "street": p.get("full_street_name") or ""}})
    logger.info("Austin bike facilities with comfort rating: %d", len(feats))
    return {"type": "FeatureCollection", "features": feats}


def fetch_counters(bbox, days: int = 60) -> list[dict]:
    """Bike counter sites with average daily bike count over the last `days`."""
    flows = _socrata(config.AUSTIN_COUNTER_FLOWS, {"travelmode": "bike"})
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    sites: dict[str, dict] = {}
    for f in flows:
        loc = (f.get("location") or {}).get("coordinates")
        name = f.get("site_name", "")
        if not loc or not _in_box(loc[1], loc[0], bbox) or "Decommissioned" in name or "Do not import" in name:
            continue
        if (f.get("site_lastdata") or "") < since:   # no data in the window
            continue
        site = sites.setdefault(f["site_id"], {"name": f["site_name"].strip(), "lat": loc[1], "lon": loc[0],
                                               "flows": [], "last": f.get("site_lastdata", "")[:10]})
        site["flows"].append(f["id"])
    if not sites:
        return []
    flow_ids = ",".join(f"'{fid}'" for s in sites.values() for fid in s["flows"])
    totals = _socrata(config.AUSTIN_COUNTER_COUNTS, {
        "$select": "flowid, sum(counts) AS total, min(timestamp) AS first",
        "$where": f"flowid in ({flow_ids}) AND timestamp > '{since}'", "$group": "flowid"})
    by_flow = {t["flowid"]: t for t in totals}
    out = []
    for s in sites.values():
        per_day = []
        for fid in s["flows"]:
            if fid in by_flow:
                first = datetime.fromisoformat(by_flow[fid]["first"][:19])
                span = max((datetime.now() - first).days, 1)
                per_day.append(float(by_flow[fid]["total"]) / span)
        if per_day:
            out.append({"name": s["name"], "lat": s["lat"], "lon": s["lon"],
                        "bikes_per_day": round(sum(per_day)), "last_data": s["last"]})
    logger.info("Austin bike counters with recent data: %d", len(out))
    return out


def fetch_work_zones(bbox) -> dict:
    """Active work zones (WZDx) as GeoJSON with a 'closed' flag for full closures."""
    resp = requests.get(config.AUSTIN_WZDX_URL, timeout=120, headers={"User-Agent": config.USER_AGENT})
    resp.raise_for_status()
    now = datetime.now(timezone.utc)
    feats = []
    for f in resp.json().get("features", []):
        p = f.get("properties", {})
        core = p.get("core_details", {})
        try:
            start = datetime.fromisoformat(p["start_date"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(p["end_date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if not start <= now <= end:
            continue
        coords = f["geometry"]["coordinates"]
        pts = coords if f["geometry"]["type"] == "LineString" else [c for part in coords for c in part]
        if not any(_in_box(lat, lon, bbox) for lon, lat in pts):
            continue
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            "closed": p.get("vehicle_impact") == "all-lanes-closed",
            "impact": p.get("vehicle_impact", ""), "road": ", ".join(core.get("road_names", [])),
            "until": p["end_date"][:10], "description": (core.get("description") or "")[:200]}})
    logger.info("Active work zones in region: %d (%d full closures)", len(feats), sum(f["properties"]["closed"] for f in feats))
    return {"type": "FeatureCollection", "features": feats, "fetched": time.time()}


def cache(name: str, region: str, data) -> None:
    (config.DATA_DIR / f"{name}_{region}.json").write_text(json.dumps(data))


def load_cached(name: str, region: str, default=None):
    path = config.DATA_DIR / f"{name}_{region}.json"
    return json.loads(path.read_text()) if path.exists() else default
