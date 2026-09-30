"""GPX and GeoJSON export (extends pyNav's route exporters with elevation and cues)."""

from xml.sax.saxutils import escape

from cycleroutes.routing.directions import cue_sheet
from cycleroutes.routing.route import Route


def _track_points(route: Route) -> list[tuple[float, float, float | None]]:
    """(lat, lon, elevation) per vertex, elevation interpolated from edge profiles."""
    pts = []
    for d in route.edge_data():
        coords = list(d["geometry"].coords)
        prof = d.get("elev_profile") or []
        for i, (lon, lat) in enumerate(coords):
            if pts and i == 0:
                continue
            ele = None
            if prof:
                ele = prof[round(i / max(len(coords) - 1, 1) * (len(prof) - 1))]
            pts.append((lat, lon, ele))
    return pts


def to_gpx(route: Route, name: str = "Cycle route") -> str:
    """GPX 1.1 with the track plus turn cues as waypoints (Garmin/Wahoo friendly)."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="CycleRoutes" xmlns="http://www.topografix.com/GPX/1/1">',
             f"  <metadata><name>{escape(name)}</name></metadata>"]
    for cue in cue_sheet(route):
        lines.append(f'  <wpt lat="{cue.lat:.6f}" lon="{cue.lon:.6f}"><name>{escape(cue.instruction)}'
                     f"</name><desc>{cue.at_km:.2f} km</desc></wpt>")
    lines.append(f"  <trk><name>{escape(name)}</name><trkseg>")
    for lat, lon, ele in _track_points(route):
        ele_tag = f"<ele>{ele:.1f}</ele>" if ele is not None else ""
        lines.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}">{ele_tag}</trkpt>')
    lines += ["  </trkseg></trk>", "</gpx>"]
    return "\n".join(lines)


def _round(coords, nd=5):
    return [[round(x, nd), round(y, nd)] for x, y in coords]


def route_segments_geojson(route: Route) -> dict:
    """Route as a FeatureCollection of edges carrying their stress/safety data,
    so the map can colour each stretch."""
    feats = []
    for d in route.edge_data():
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": _round(d["geometry"].coords)},
            "properties": {"lts": d["lts"], "safety": round(d["safety"], 2),
                           "fun": round(d["fun"], 2), "name": str(d.get("name", "") or "")},
        })
    return {"type": "FeatureCollection", "features": feats}


def network_geojson(graph, min_length_m: float = 0.0) -> dict:
    """Whole network coloured by LTS (one feature per undirected street segment)."""
    seen, feats = set(), []
    for u, v, d in graph.edges(data=True):
        key = (min(u, v), max(u, v))
        if key in seen or d["length"] < min_length_m:
            continue
        seen.add(key)
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": _round(d["geometry"].coords)},
            "properties": {"lts": d["lts"], "route": d.get("route_rank", 0)},
        })
    return {"type": "FeatureCollection", "features": feats}
