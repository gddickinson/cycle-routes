"""Per-area data-source choices (data_cache/settings_<area>.json), editable in the app.

network:   "auto" (a downloaded extract if one covers the area, else Overpass) | "extract" | "overpass"
elevation: "auto" (USGS 3DEP in the US, else Copernicus) | "3dep" | "copernicus"
prefer_cached: reuse data already downloaded where it covers the area
layers:    optional open-data layers used in scoring (on/off)
"""

import json

from cycleroutes import config

LAYERS = {
    "canopy": "Tree shade (Meta/WRI canopy)",
    "noise": "Road & aviation noise (US DOT)",
    "aadt": "Measured traffic volumes (TxDOT)",
    "comfort": "City bike-comfort ratings (Austin)",
    "crashes": "Bike crash records (Austin Vision Zero)",
    "counters": "Bike counters (Austin)",
    "stops": "Cafés, food, sights (Overture Maps)",
    "amenities": "Water, toilets, bike shops (OSM)",
}
DEFAULTS = {"network": "auto", "elevation": "auto", "prefer_cached": True, "layers": {k: True for k in LAYERS}}
CHOICES = {"network": ("auto", "extract", "overpass"), "elevation": ("auto", "3dep", "copernicus")}


def path(region: str):
    return config.DATA_DIR / f"settings_{region}.json"


def load(region: str) -> dict:
    p = path(region)
    saved = json.loads(p.read_text()) if p.exists() else {}
    merged = {**DEFAULTS, **{k: v for k, v in saved.items() if k != "layers"}}
    merged["layers"] = {**DEFAULTS["layers"], **saved.get("layers", {})}
    return merged


def validate(changes: dict) -> dict:
    out = {}
    for key, allowed in CHOICES.items():
        if key in changes:
            if changes[key] not in allowed:
                raise ValueError(f"{key} must be one of {', '.join(allowed)}")
            out[key] = changes[key]
    if "prefer_cached" in changes:
        out["prefer_cached"] = bool(changes["prefer_cached"])
    if "layers" in changes:
        unknown = set(changes["layers"]) - set(LAYERS)
        if unknown:
            raise ValueError(f"Unknown layers: {', '.join(sorted(unknown))}")
        out["layers"] = {k: bool(v) for k, v in changes["layers"].items()}
    return out


def save(region: str, changes: dict) -> dict:
    current = load(region)
    ok = validate(changes)
    current.update({k: v for k, v in ok.items() if k != "layers"})
    current["layers"].update(ok.get("layers", {}))
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path(region).write_text(json.dumps(current, indent=1))
    return current
