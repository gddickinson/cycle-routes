"""Stops worth riding to from Overture Maps places (cafés, bakeries, ice cream, viewpoints...)."""

import json
import logging

from cycleroutes import config

logger = logging.getLogger(__name__)

# Overture basic_category -> our stop category
STOP_CATEGORIES = {
    "coffee_shop": "cafe", "cafe": "cafe", "bakery": "cafe", "dessert_shop": "treat",
    "ice_cream_shop": "treat", "casual_eatery": "food", "restaurant": "food", "brewery": "food",
    "grocery_store": "shop", "convenience_store": "shop", "bicycle_shop": "bike_shop",
    "park": "park", "landmark_and_historical_building": "landmark", "viewpoint": "landmark",
    "museum": "landmark", "swimming_pool": "swim", "beach": "swim",
    "hotel": "stay", "motel": "stay", "bed_and_breakfast": "stay", "hostel": "stay",
    "campground": "stay", "rv_park": "stay",
}
MIN_CONFIDENCE = 0.6


def fetch_places(bbox) -> dict:
    """GeoJSON of stops inside bbox (DuckDB reads the public S3 GeoParquet directly)."""
    import duckdb
    s, w, n, e = bbox
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    cats = ",".join(f"'{c}'" for c in STOP_CATEGORIES)
    rows = con.execute(f"""
        SELECT names."primary", basic_category, taxonomy."primary", confidence,
               (bbox.xmin + bbox.xmax) / 2, (bbox.ymin + bbox.ymax) / 2, websites[1]
        FROM read_parquet('{config.OVERTURE_PLACES}', hive_partitioning=1)
        WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n}
          AND confidence >= {MIN_CONFIDENCE}
          AND (basic_category IN ({cats}) OR taxonomy."primary" IN ({cats}))""").fetchall()
    feats = []
    for name, basic, primary, conf, lon, lat, web in rows:
        cat = STOP_CATEGORIES.get(primary) or STOP_CATEGORIES.get(basic)
        if not name or not cat:
            continue
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                      "properties": {"name": name, "category": cat, "kind": primary or basic,
                                     "confidence": round(conf, 2), **({"website": web} if web else {})}})
    logger.info("Overture stops: %d", len(feats))
    return {"type": "FeatureCollection", "features": feats}


def save(region: str, geo: dict) -> None:
    (config.DATA_DIR / f"stops_{region}.geojson").write_text(json.dumps(geo))


def load(region: str) -> dict:
    p = config.DATA_DIR / f"stops_{region}.geojson"
    return json.loads(p.read_text()) if p.exists() else {"type": "FeatureCollection", "features": []}
