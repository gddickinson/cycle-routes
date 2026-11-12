"""FastAPI web app for the Cycle Routes showcase site: serves the front end in static/ and the JSON API under /api.

Run with `python run_web.py` (http://127.0.0.1:8184, local only). `scripts/build_static.py` exports every path in
STATIC_ENDPOINTS to JSON for the GitHub Pages site, so keep that list in step with the GET routes below. Everything
here runs on the committed demo area (no downloads); the full route planner for your own area is
`cycleroutes serve` (cycleroutes/api/app.py), which needs an area built from OpenStreetMap with `cycleroutes build`.
"""
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from cycleroutes import config
from cycleroutes.routing.context import BIKE_AVOID, BIKE_TYPES, RouteContext
from cycleroutes.routing.router import Router, RoutingError
from cycleroutes.scoring.edge_attrs import add_scores
from cycleroutes.web import demo_area, examples
from cycleroutes.web.model import model

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Cycle Routes")
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.get("/static/{path:path}", include_in_schema=False)
def static_file(path: str):
    """Static files, never cached, so an edited module is picked up on reload during development."""
    target = (STATIC / path).resolve()
    if STATIC not in target.parents or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.exception_handler(RoutingError)
async def routing_error(_, exc: RoutingError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/info")
def info():
    """Project summary and demo-area facts for the home page."""
    area = demo_area.load_demo()["area"]
    return {"title": "Cycle Routes", "tagline": "Low-stress, fun bike rides and walks, generated automatically "
            "from open data", "area": area, "summary": demo_area.summary(),
            "profiles": len(config.PROFILES), "walk_profiles": len(config.WALK_PROFILES),
            "bike_types": len(BIKE_TYPES), "avoid_types": len(BIKE_AVOID),
            "safety_notice": config.SAFETY_NOTICE}


@app.get("/api/model")
def model_json():
    """Every table and weight the browser engine uses, taken from the Python modules."""
    return model()


@app.get("/api/demo")
def demo():
    """The demo area's compact street graph (raw OSM tags + enrichment; scores are recomputed by the client)."""
    return Response(demo_area.demo_path().read_bytes(), media_type="application/json")


@app.get("/api/examples")
def example_routes():
    """A->B alternatives and suggested loops computed by the Python router on the demo area."""
    return examples.examples()


# --- local-app only (POST / filesystem): the static site answers these in the browser or explains -------------
def _ctx(body: dict) -> RouteContext:
    avoid = set(body.get("avoid") or [])
    if avoid - set(BIKE_AVOID):
        raise HTTPException(400, f"Unknown avoid option(s): {', '.join(sorted(avoid - set(BIKE_AVOID)))}")
    bike = body.get("bike", "hybrid")
    if bike not in BIKE_TYPES:
        raise HTTPException(400, f"Unknown bike type '{bike}'")
    return RouteContext(bike=bike, dark=bool(body.get("dark")), wind_kmh=float(body.get("wind_kmh") or 0),
                        wind_from_deg=float(body.get("wind_from_deg") or 0), avoid=frozenset(avoid),
                        infra_only=bool(body.get("infra_only")))


def _point(p) -> tuple[float, float]:
    try:
        lat, lon = (float(x) for x in p)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Points are [lat, lon]") from exc
    return lat, lon


@app.post("/api/route")
def python_route(body: dict = Body(...)):
    """Alternatives from the Python router on the demo area (the browser compares them with its own)."""
    router = Router(demo_area.load_graph())
    return examples.alternatives_json(router, _point(body.get("start")), _point(body.get("end")), _ctx(body))


@app.post("/api/loop")
def python_loop(body: dict = Body(...)):
    profile = body.get("profile", "scenic")
    if profile not in config.PROFILES:
        raise HTTPException(400, f"Unknown profile '{profile}'")
    km = float(body.get("km", 5))
    if not 1 <= km <= 30:
        raise HTTPException(400, "km must be between 1 and 30")
    router = Router(demo_area.load_graph())
    return examples.loops_json(router, _point(body.get("start")), km, profile, int(body.get("count", 3)), _ctx(body))


SCORE_FIELDS = ("lts", "lts_osm", "safety", "quiet", "surface_q", "fun", "time_s", "trail", "bike_infra",
                "mtb_scale", "awkward")


@app.post("/api/score")
def python_score(body: dict = Body(...)):
    """Score one street from its OSM tags with the Python scoring code (body: {tags: {...}, length, ascent, ...})."""
    import networkx as nx
    from shapely.geometry import LineString
    tags = {str(k): v for k, v in (body.get("tags") or {}).items() if v not in (None, "")}
    edge = {**tags, "length": float(body.get("length", 100)), "scenic": float(body.get("scenic", 0)),
            "ascent": float(body.get("ascent", 0)), "descent": float(body.get("descent", 0)),
            "route_rank": int(body.get("route_rank", 0))}
    for key in ("aadt", "noise_db", "shade", "crashes", "crashes_severe"):
        if body.get(key) not in (None, ""):
            edge[key] = float(body[key])
    g = nx.MultiDiGraph()
    g.add_node(0, x=0.0, y=0.0)
    g.add_node(1, x=0.0, y=0.001)
    g.add_edge(0, 1, geometry=LineString([(0, 0), (0, 0.001)]), **edge)
    add_scores(g)
    d = g.edges[0, 1, 0]
    return {k: d[k] for k in SCORE_FIELDS}


@app.get("/api/areas")
def built_areas():
    """Areas built on this machine with `cycleroutes build` (open them in the full planner, `cycleroutes serve`)."""
    index_file = config.DATA_DIR / "regions.json"
    if not index_file.exists():
        return {"areas": [], "data_dir": str(config.DATA_DIR)}
    import json
    index = json.loads(index_file.read_text())
    areas = [{"name": k, "bbox": v.get("bbox"), "network": v.get("network", ""),
              "built": v.get("built")} for k, v in index.items() if (config.DATA_DIR / f"region_{k}.pkl").exists()]
    return {"areas": areas, "data_dir": str(config.DATA_DIR)}


# GET paths (without the /api prefix) written to the static site as api/<path>.json.
STATIC_ENDPOINTS = ["/info", "/model", "/demo", "/examples"]
