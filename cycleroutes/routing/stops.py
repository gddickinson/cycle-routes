"""Useful stops along a route: water, toilets, bike shops, cafés, bike share...

Also finds the longest stretch without drinking water (matters in Texas heat).
"""

import numpy as np

from cycleroutes.routing.route import Route

EARTH_M_PER_DEG = 111_320.0
GROUPS = {   # stop category -> UI group
    "water": "water", "toilets": "toilets", "bike_shop": "bike", "repair": "bike",
    "bike_share": "bike_share", "cafe": "food", "treat": "food", "food": "food", "shop": "food",
    "park": "sights", "landmark": "sights", "swim": "sights", "stay": "stay", "parking": "parking",
}


def _route_xy(route: Route):
    coords = np.array(route.coords())
    lat0 = float(coords[:, 1].mean())
    kx = EARTH_M_PER_DEG * np.cos(np.radians(lat0))
    xy = np.column_stack([coords[:, 0] * kx, coords[:, 1] * EARTH_M_PER_DEG])
    seg = np.diff(xy, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    return xy, seg, seg_len, np.concatenate([[0.0], np.cumsum(seg_len)]), kx


def along(route: Route, features: list[dict], within_m: float = 150.0) -> list[dict]:
    """Features within `within_m` of the route, with km along and metres off route."""
    xy, seg, seg_len, cum, kx = _route_xy(route)
    L2 = np.maximum(seg_len ** 2, 1e-9)
    out = []
    for f in features:
        lon, lat = f["geometry"]["coordinates"][:2]
        x, y = lon * kx, lat * EARTH_M_PER_DEG
        t = np.clip(((x - xy[:-1, 0]) * seg[:, 0] + (y - xy[:-1, 1]) * seg[:, 1]) / L2, 0, 1)
        d = np.hypot(xy[:-1, 0] + t * seg[:, 0] - x, xy[:-1, 1] + t * seg[:, 1] - y)
        i = int(np.argmin(d))
        if d[i] <= within_m:
            p = dict(f["properties"])
            cat = p.get("category", "")
            out.append(p | {"lat": lat, "lon": lon, "group": GROUPS.get(cat, "other"),
                            "at_km": round(float(cum[i] + t[i] * seg_len[i]) / 1000, 2),
                            "off_route_m": round(float(d[i]))})
    out.sort(key=lambda s: s["at_km"])
    return out


def longest_dry_stretch(route: Route, stops: list[dict]) -> float:
    """Longest distance (km) between drinking-water opportunities (start/end count)."""
    marks = [0.0] + [s["at_km"] for s in stops if s["group"] in ("water", "food")] + [route.length_m / 1000]
    marks.sort()
    return round(max(b - a for a, b in zip(marks[:-1], marks[1:])), 2)
