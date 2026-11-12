"""Write tests/fixtures/engine_parity.json: Python results the JS engine must reproduce (static/engine.test.mjs).

Everything is computed by the package's own code on the committed demo area (no downloads):
edge scores (sampled demo edges + synthetic tag sets that reach every branch, incl. measured-traffic data), risky
crossings, A->B alternatives under several riding contexts, loops, cue sheets, and Python round()/numpy sums.

Run: python scripts/make_engine_fixtures.py     (tests/test_web.py checks the fixture is current)
"""
import json
import random
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycleroutes.routing.context import RouteContext  # noqa: E402
from cycleroutes.routing.router import Router  # noqa: E402
from cycleroutes.scoring.edge_attrs import add_scores  # noqa: E402
from cycleroutes.web import demo_area, examples  # noqa: E402
from cycleroutes.web.model import model  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "engine_parity.json"
SCORE_KEYS = ("bearing", "trail", "mtb_scale", "bike_infra", "lts_osm", "lts", "safety", "quiet", "surface_q", "fun",
              "time_s", "safety_osm", "quiet_osm", "fun_osm", "awkward")
EDGE_SAMPLE_STEP = 9

SYNTHETIC = [
    {"highway": "primary", "lanes": "4", "maxspeed": "45 mph", "name": "Fast Road"},
    {"highway": "secondary", "maxspeed": "30 mph", "cycleway:right": "lane", "lanes": "2"},
    {"highway": "tertiary", "maxspeed": "35 mph", "cycleway": "buffered_lane", "lanes": "3"},
    {"highway": "primary_link", "maxspeed": "60", "cycleway:both": "lane", "lanes": "6"},
    {"highway": "residential", "maxspeed": "25 mph", "lit": "yes"},
    {"highway": "residential", "maxspeed": "30 mph", "lanes": "2;3"},
    {"highway": "residential", "maxspeed": "35 mph"},
    {"highway": "unclassified", "maxspeed": "signals", "lanes": "abc"},
    {"highway": ["residential", "tertiary"], "maxspeed": ["25 mph", "30 mph"], "name": ["A St", "B St"]},
    {"highway": "living_street"}, {"highway": "steps", "surface": "concrete"},
    {"highway": "service", "service": "parking_aisle"}, {"highway": "service", "service": ["driveway", "alley"]},
    {"highway": "cycleway", "name": "Shoal Creek Trail", "surface": "asphalt"},
    {"highway": "cycleway", "name": "Main Street cycle track"},
    {"highway": "footway", "footway": "sidewalk", "bicycle": "yes"}, {"highway": "footway", "bicycle": "designated"},
    {"highway": "path", "surface": "dirt", "mtb:scale": "2+"}, {"highway": "track", "mtb:scale": "1", "bicycle": "no"},
    {"highway": "bridleway"}, {"highway": "pedestrian", "surface": "sett"},
    {"highway": "trunk", "cycleway": "track"}, {"highway": "road", "surface": "gravel;dirt"},
    {"highway": "tertiary", "cycleway:left": "shared_lane", "surface": ["asphalt", "paving_stones"]},
]
# (tags index, extra open-data attributes) for the measured-data branches
MEASURED = [(4, {"aadt": 25000}), (1, {"aadt": 9000}), (4, {"aadt": 900, "maxspeed": "30 mph"}),
            (5, {"aadt": 1200}), (0, {"noise_db": 70, "crashes": 2, "crashes_severe": 1}),
            (13, {"shade": 0.8, "noise_db": 50}), (6, {"city_lts": 1}), (1, {"city_lts": 4, "city_facility": "Protected bike lane"}),
            (9, {"crashes": 9})]

CONTEXTS = {
    "default": {},
    "ebike_dark": {"bike": "ebike", "dark": True},
    "avoid_infra": {"avoid": ["major", "busy", "unpaved"], "infra_only": True},
    "kids_wind": {"bike": "kids", "wind_kmh": 22.0, "wind_from_deg": 270.0},
    "road_avoid": {"bike": "road", "avoid": ["stressful", "service", "steps"]},
    "mtb_avoid": {"bike": "mtb", "avoid": ["sidewalks", "secondary", "trails"]},
}
LOOPS = [("scenic", 4.0, "default"), ("family", 3.0, "avoid_infra"), ("trails", 5.0, "ebike_dark"), ("flattest", 2.5, "kids_wind")]
OD_PAIRS = 12


def ctx_of(spec: dict) -> RouteContext:
    return RouteContext(bike=spec.get("bike", "hybrid"), dark=spec.get("dark", False),
                        wind_kmh=spec.get("wind_kmh", 0.0), wind_from_deg=spec.get("wind_from_deg", 0.0),
                        avoid=frozenset(spec.get("avoid", [])), infra_only=spec.get("infra_only", False))


def score_tags(edge: dict) -> dict:
    g = nx.MultiDiGraph()
    g.add_node(0, x=-73.97, y=40.66)
    g.add_node(1, x=-73.969, y=40.661)
    g.add_edge(0, 1, geometry=LineString([(-73.97, 40.66), (-73.969, 40.661)]), **edge)
    add_scores(g)
    d = g.edges[0, 1, 0]
    return {k: d[k] for k in SCORE_KEYS}


def synthetic_cases() -> list[dict]:
    cases = []
    base = {"length": 150.0, "scenic": 0.25, "ascent": 3.0, "descent": 0.5, "route_rank": 0}
    for i, tags in enumerate(SYNTHETIC):
        extra = {"route_rank": 1} if i % 5 == 0 else {}
        edge = {**base, **tags, **extra, **({"ascent": 0.0, "descent": 6.0} if i % 4 == 1 else {})}
        cases.append({"edge": edge, "py": score_tags(edge)})
    for idx, attrs in MEASURED:
        edge = {**base, **SYNTHETIC[idx], **attrs}
        cases.append({"edge": edge, "py": score_tags(edge)})
    return cases


def build_fixture() -> dict:
    demo = demo_area.load_demo()
    g = demo_area.load_graph()
    edges = list(g.edges(keys=True, data=True))
    sampled = sorted(set(range(0, len(edges), EDGE_SAMPLE_STEP)) | {i for i, row in enumerate(demo["edges"])
                                                                     if row[3] < 200 and row[3] % 3 == 0})
    edge_scores = [{"uvk": list(edges[i][:3]), **{k: edges[i][3][k] for k in SCORE_KEYS}} for i in sampled]
    risky = {str(n): list(d["busy_names"]) for n, d in g.nodes(data=True) if d.get("risky_crossing")}

    router = Router(g)
    rnd = random.Random(7)
    lats, lons = demo["nodes"]["lat"], demo["nodes"]["lon"]
    s, w, n, e = demo["area"]["bbox"]
    pairs = []
    while len(pairs) < OD_PAIRS:
        a = [rnd.uniform(s, n), rnd.uniform(w, e)]
        b = [rnd.uniform(s, n), rnd.uniform(w, e)]
        pairs.append((a, b))
    routes = []
    for i, (a, b) in enumerate(pairs):
        for name in list(CONTEXTS)[i % 3::3][:2] if i else CONTEXTS:
            routes.append({"start": a, "end": b, "ctx": name,
                           "routes": examples.alternatives_json(router, a, b, ctx_of(CONTEXTS[name]))})
    loops = []
    hubs = demo["area"]["hubs"]
    for j, (profile, km, cname) in enumerate(LOOPS):
        h = hubs[j % len(hubs)]
        start = [h["lat"], h["lon"]]
        loops.append({"start": start, "km": km, "profile": profile, "ctx": cname,
                      "routes": examples.loops_json(router, start, km, profile, 3, ctx_of(CONTEXTS[cname]))})

    nums = [rnd.uniform(0, 30) for _ in range(40)] + [0.25, 2.25, 0.125, 1.005, 2.675, 0.15, 12.5, 13.5, -2.5, 7.45]
    arrays = [[rnd.uniform(1, 300) for _ in range(k)] for k in (3, 8, 9, 17, 130, 257, 1000)]
    return {"model": model(), "node_count": len(lats), "edge_count": len(edges), "contexts": CONTEXTS, "edge_scores": edge_scores,
            "synthetic": synthetic_cases(), "risky": risky, "routes": routes, "loops": loops,
            "round_cases": [[x, d, round(x, d)] for x in nums for d in (0, 1, 2)],
            "sum_cases": [[a, float(np.array(a).sum())] for a in arrays],
            "pysum_cases": [[a, sum(a)] for a in arrays + [[0.1] * 10, [1e16, 1.0, -1e16], [1.1, 0.4, 2.0, 0.0]]]}


def main():
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    fx = build_fixture()
    FIXTURE.write_text(json.dumps(fx, separators=(",", ":")))
    print(f"{FIXTURE}: {len(fx['edge_scores'])} edges, {len(fx['synthetic'])} tag cases, "
          f"{sum(len(r['routes']) for r in fx['routes'])} routes, {sum(len(x['routes']) for x in fx['loops'])} loops, "
          f"{FIXTURE.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
