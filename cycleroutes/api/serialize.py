"""Route -> JSON payloads for the web client."""

from cycleroutes import config
from cycleroutes.export.formats import route_segments_geojson
from cycleroutes.routing.directions import cue_sheet
from cycleroutes.routing.route import Route

MAX_PROFILE_POINTS = 300


def _downsample_profile(route: Route) -> list[list[float]]:
    prof = route.elevation_profile()
    step = max(1, len(prof) // MAX_PROFILE_POINTS)
    pts = prof[::step]
    if prof and pts[-1] != prof[-1]:
        pts.append(prof[-1])
    return [[round(d / 1000, 3), round(z, 1)] for d, z in pts]


def profile_label(name: str, mode: str = "bike") -> str:
    if name == "ridden":
        return "Your trip" if mode == "walk" else "Your ride"
    prof = config.MODES.get(mode, config.PROFILES).get(name)
    return prof.label if prof else "Custom"


def route_payload(route_id: str, route: Route, stats: dict, title: str | None = None) -> dict:
    mode = route.graph.graph.get("mode", "bike")
    also = [profile_label(p, mode) for p in route.meta.get("also_matches", [])]
    return {
        "id": route_id,
        "title": title or route.meta.get("title") or profile_label(route.profile, mode),
        "mode": mode,
        "profile": route.profile,
        "profile_label": profile_label(route.profile, mode),
        "tour": route.meta.get("tour"),
        "legs": route.meta.get("legs"),
        "planned_stops": route.meta.get("planned_stops"),
        "missing_stops": route.meta.get("missing_stops"),
        "also_best_for": also,
        "kind": route.kind,
        "stats": stats,
        "geojson": route_segments_geojson(route),
        "cues": [c.to_dict() for c in cue_sheet(route)],
        "elevation": _downsample_profile(route),
    }
