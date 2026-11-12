"""Write the web demo area (cycleroutes/web/demo/<name>.json) from a region built with `cycleroutes build`.

Needs the full install (osmnx, geopandas...) and a built region in data_cache/; run locally, never in CI:

    cycleroutes build --name prospect_park --lat 40.6602 --lon -73.9690 --radius 1600   # Overpass + DEM download
    python scripts/make_demo_area.py --region prospect_park --title "Prospect Park, Brooklyn"

The JSON keeps raw OSM tags (as tag sets shared by many edges) and the GIS-derived enrichment; every score is
recomputed from it by cycleroutes/web/demo_area.py (Python) and static/demo_graph.js (browser). The script checks that
the rebuilt graph scores exactly like the region it came from.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycleroutes.data.region import load_region, region_index  # noqa: E402
from cycleroutes.routing.catalog import pick_hubs  # noqa: E402
from cycleroutes.routing.geo import haversine_m  # noqa: E402
from cycleroutes.web import demo_area  # noqa: E402

# OSM tags the scoring, routing, directions and avoid options read (plus oneway, shown in the street inspector)
TAG_KEYS = ("highway", "name", "maxspeed", "lanes", "cycleway", "cycleway:left", "cycleway:right", "cycleway:both",
            "bicycle", "footway", "mtb:scale", "surface", "lit", "service", "bridge", "tunnel", "oneway")
MIN_HUB_SPACING_M = 500
SCORE_KEYS = ("lts", "lts_osm", "safety", "quiet", "fun", "surface_q", "time_s", "awkward", "trail", "bike_infra")


def _clean(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value)


def export(region_name: str, title: str) -> dict:
    region = load_region(region_name)
    g = region.graph
    ids = {n: i for i, n in enumerate(g.nodes)}
    tagsets, tag_index, geoms, elev, geom_index, names, names_index, edges = [], {}, [], [], {}, [], {}, []
    for u, v, k, d in g.edges(keys=True, data=True):
        tags = {key: _clean(d.get(key)) for key in TAG_KEYS}
        tags = {key: val for key, val in tags.items() if val is not None}
        tkey = json.dumps(tags, sort_keys=True)
        if tkey not in tag_index:
            tag_index[tkey] = len(tagsets)
            tagsets.append(tags)
        coords = tuple(round(c, 6) for xy in d["geometry"].coords for c in xy)
        prof = tuple(round(float(z), 1) for z in d.get("elev_profile") or [])
        rev = tuple(c for i in range(len(coords) - 2, -1, -2) for c in coords[i:i + 2])
        if (rev, prof[::-1]) in geom_index:
            gi = -geom_index[(rev, prof[::-1])] - 1
        else:
            gi = geom_index.setdefault((coords, prof), len(geoms))
            if gi == len(geoms):
                geoms.append(list(coords))
                elev.append(list(prof))
        rn = tuple(d.get("route_names") or [])
        ni = -1
        if rn:
            ni = names_index.setdefault(rn, len(names))
            if ni == len(names):
                names.append(list(rn))
        edges.append([ids[u], ids[v], int(k), tag_index[tkey], float(d["length"]),
                      round(float(d.get("scenic", 0.0)), 4), float(d.get("ascent", 0.0)),
                      float(d.get("descent", 0.0)), int(d.get("route_rank", 0)), gi, ni])
    built = region_index().get(region_name, {}).get("built")
    hubs = []
    for h in pick_hubs(region):      # centre + largest named parks; skip a park whose point is next to an earlier hub
        if all(haversine_m(h["lat"], h["lon"], o["lat"], o["lon"]) > MIN_HUB_SPACING_M for o in hubs):
            hubs.append(h)
    hubs[0]["name"] = f"{title.split(',')[0]} (area centre)"
    return {
        "area": {"name": region_name, "title": title, "lat": region.lat, "lon": region.lon,
                 "radius_m": region.radius_m, "bbox": [round(b, 6) for b in region.bbox],
                 "built": time.strftime("%Y-%m-%d", time.localtime(built)) if built else None,
                 "sources": {k: str(v) for k, v in region.sources.items()},
                 "hubs": [{"name": h["name"], "lat": round(h["lat"], 6), "lon": round(h["lon"], 6)} for h in hubs]},
        "nodes": {"lat": [round(g.nodes[n]["y"], 7) for n in g.nodes], "lon": [round(g.nodes[n]["x"], 7) for n in g.nodes],
                  "signals": [ids[n] for n, nd in g.nodes(data=True) if nd.get("highway") == "traffic_signals"]},
        "tagsets": tagsets, "edges": edges, "geoms": geoms, "elev": elev, "route_names": names,
    }, region


def check(demo: dict, region) -> list[str]:
    """Differences between the region's scores and the rebuilt demo graph's (expected: none beyond rounding)."""
    rebuilt = demo_area.graph_from_demo(demo)
    ids = {n: i for i, n in enumerate(region.graph.nodes)}
    problems = []
    for u, v, k, d in region.graph.edges(keys=True, data=True):
        r = rebuilt.edges[ids[u], ids[v], k]
        for key in SCORE_KEYS:
            a, b = d[key], r[key]
            if isinstance(a, float) and abs(a - b) > 1e-3 * max(1.0, abs(a)) or not isinstance(a, float) and a != b:
                problems.append(f"edge {u}->{v} {key}: region {a} vs demo {b}")
    for n, nd in region.graph.nodes(data=True):
        if bool(nd.get("risky_crossing")) != bool(rebuilt.nodes[ids[n]].get("risky_crossing")):
            problems.append(f"node {n} risky_crossing differs")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=demo_area.DEMO_AREA)
    ap.add_argument("--title", default="Prospect Park, Brooklyn")
    a = ap.parse_args()
    demo, region = export(a.region, a.title)
    problems = check(demo, region)
    for p in problems[:20]:
        print("MISMATCH", p)
    out = demo_area.demo_path(a.region)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(demo, ensure_ascii=False, separators=(",", ":")))
    print(f"{out}: {len(demo['nodes']['lat'])} nodes, {len(demo['edges'])} edges, {len(demo['tagsets'])} tag sets, "
          f"{out.stat().st_size / 1e6:.2f} MB; {len(problems)} score mismatches")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
