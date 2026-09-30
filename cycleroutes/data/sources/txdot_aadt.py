"""Measured motor-traffic volumes (AADT) from TxDOT count stations (Texas only).

Stations are points; each is snapped to the nearest drivable street segment and
its volume spread along the same-named street, so every nearby block of that
street gets a measured rather than guessed traffic level.
"""

import logging

import requests

from cycleroutes import config

logger = logging.getLogger(__name__)


def covers(south: float, west: float, north: float, east: float) -> bool:
    s, w, n, e = config.TEXAS_BBOX
    return s <= south and north <= n and w <= west and east <= e


def fetch_stations(bbox) -> list[dict]:
    """[{lat, lon, aadt, year}] from TxDOT annual + 5-year count layers."""
    s, w, n, e = bbox
    out = []
    for url in config.TXDOT_AADT_URLS:
        offset = 0
        while True:
            resp = requests.get(f"{url}/query", timeout=120, headers={"User-Agent": config.USER_AGENT}, params={
                "geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                "outSR": 4326, "outFields": "*", "resultOffset": offset, "resultRecordCount": 2000, "f": "json"})
            resp.raise_for_status()
            data = resp.json()
            for f in data.get("features", []):
                a = f["attributes"]
                qty = a.get("AADT_RPT_QTY")
                if qty:
                    out.append({"lat": f["geometry"]["y"], "lon": f["geometry"]["x"], "aadt": int(qty),
                                "year": a.get("AADT_RPT_YEAR") or a.get("LATEST_AADT_YR")})
            if not data.get("exceededTransferLimit"):
                break
            offset += 2000
    logger.info("TxDOT AADT stations in region: %d", len(out))
    return out
