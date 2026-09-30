"""Helpers for reading messy OSM tag values off simplified osmnx edges.

After simplification an edge attribute may be a scalar, a list (merged ways) or
missing/NaN. These helpers normalise that.
"""

import math
import re

from cycleroutes import config

HIGHWAY_ORDER = ["trunk", "primary", "secondary", "tertiary", "unclassified",
                 "road", "residential", "service", "living_street",
                 "track", "path", "bridleway", "footway", "pedestrian", "steps", "cycleway"]


def values(edge: dict, key: str) -> list[str]:
    """All values of a tag as lowercase strings (empty list if absent)."""
    raw = edge.get(key)
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [str(v).strip().lower() for v in items if v is not None]


def first(edge: dict, key: str, default: str = "") -> str:
    vals = values(edge, key)
    return vals[0] if vals else default


def highway(edge: dict) -> str:
    """Dominant (most car-like) highway class of an edge."""
    hw = [h.replace("_link", "") for h in values(edge, "highway")]
    for cls in HIGHWAY_ORDER:
        if cls in hw:
            return cls
    return hw[0] if hw else "road"


def parse_speed_kmh(value: str) -> float | None:
    """'30 mph' -> 48.3, '50' -> 50, 'none'/'signals' -> None."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kmh)?", value)
    if not m:
        return None
    speed = float(m.group(1))
    return speed * 1.609 if m.group(2) == "mph" else speed


def speed_limit_kmh(edge: dict) -> float:
    speeds = [s for s in (parse_speed_kmh(v) for v in values(edge, "maxspeed")) if s]
    if speeds:
        return max(speeds)
    return config.DEFAULT_SPEED_KMH.get(highway(edge), 40)


def lanes(edge: dict) -> int:
    nums = []
    for v in values(edge, "lanes"):
        try:
            nums.append(int(float(v.split(";")[0])))
        except ValueError:
            pass
    if nums:
        return max(nums)
    return 4 if highway(edge) in ("trunk", "primary") else 2


def cycleway_kind(edge: dict) -> str:
    """'track' (separated), 'lane' (painted), 'shared' or '' (none)."""
    vals = []
    for key in ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right"):
        vals += values(edge, key)
    if any(v in ("track", "separate", "opposite_track") for v in vals):
        return "track"
    if any(v in ("lane", "opposite_lane", "buffered_lane") for v in vals):
        return "lane"
    if any(v in ("shared_lane", "share_busway", "shared") for v in vals):
        return "shared"
    return ""


def is_yes(edge: dict, key: str) -> bool:
    return any(v not in ("no", "false", "0", "") for v in values(edge, key))


TRAIL_WORDS = ("trail", "greenway", "greenbelt", "path", "hike and bike", "creek")
CITY_INFRA = ("bike lane", "protected", "trail", "cycle track")


def mtb_scale(edge: dict) -> int | None:
    """OSM mtb:scale as an int (0 easy … 6 extreme), or None."""
    for v in values(edge, "mtb:scale"):
        digits = "".join(ch for ch in v if ch.isdigit())
        if digits:
            return int(digits[0])
    return None


def is_trail(edge: dict) -> bool:
    """Off-road trail or greenway (not a sidewalk, not a lane beside a road)."""
    hw = highway(edge)
    if mtb_scale(edge) is not None:
        return True
    if hw in ("path", "track", "bridleway"):
        return True
    if hw == "footway":
        return not any(v in ("sidewalk", "crossing") for v in values(edge, "footway"))
    if hw == "cycleway":
        name = " ".join(values(edge, "name"))
        return any(w in name for w in TRAIL_WORDS)
    return False


def has_bike_infra(edge: dict) -> bool:
    """Dedicated space for bikes: cycle path/trail, painted or protected lane, or a city-mapped facility."""
    if highway(edge) == "cycleway" or cycleway_kind(edge) in ("lane", "track"):
        return True
    if is_trail(edge) and any(v in ("yes", "designated", "permissive") for v in values(edge, "bicycle")):
        return True
    if highway(edge) in ("path", "track") and not values(edge, "bicycle"):
        return True     # unmarked paths are usually open to bikes
    facility = str(edge.get("city_facility") or "").lower()
    return any(w in facility for w in CITY_INFRA)
