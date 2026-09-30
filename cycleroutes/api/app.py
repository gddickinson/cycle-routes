"""FastAPI backend + static web client.

Run:  uvicorn cycleroutes.api.app:app --reload     (region from $CYCLEROUTES_REGION)
"""

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cycleroutes import config
from cycleroutes.api.state import latlon as _latlon
from cycleroutes.api.state import state
from cycleroutes.api.community_api import router as community_router
from cycleroutes.api.offline_api import router as offline_router
from cycleroutes.api.planning_api import router as planning_router
from cycleroutes.api.sources_api import router as sources_router
from cycleroutes.api.tracking_api import router as tracking_router
from cycleroutes.export.formats import to_gpx
from cycleroutes.export.print_map import route_pdf
from cycleroutes.routing.combine import extend_route
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.planner import STOP_TYPES, plan_trip
from cycleroutes.routing.tours import generate_tour
from cycleroutes.routing.rating import rate
from cycleroutes.routing.context import AVOID_TYPES, BIKE_AVOID, BIKE_TYPES, WALK_AVOID
from cycleroutes.routing.router import RoutingError, custom_profile

app = FastAPI(title="Cycle Routes prototype")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(tracking_router)
app.include_router(planning_router)
app.include_router(community_router)
app.include_router(offline_router)
app.include_router(sources_router)


def _profile(profile: str, safety, fun, traffic, hills, surface, shade=0.0):
    if profile == "learned":
        learned = state().community.learned_weights()
        if not learned:
            raise HTTPException(404, "Not enough rides yet to learn your preferences (need 3)")
        return custom_profile(**{k: v for k, v in learned.items() if k != "based_on"})
    if profile != "custom":
        return profile
    return custom_profile(safety=safety, fun=fun, traffic=traffic, hills=hills, surface=surface, shade=shade)


@app.exception_handler(RoutingError)
async def routing_error(_, exc: RoutingError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/region")
def region_info():
    s = state()
    south, west, north, east = s.region.bbox
    return {
        "name": s.region.name, "center": [s.region.lat, s.region.lon],
        "bbox": [south, west, north, east],
        "profiles": {k: {"label": p.label, "description": p.description, **p.weights()}
                     for k, p in config.PROFILES.items()},
        "lts_colors": config.LTS_COLORS, "lts_labels": config.LTS_LABELS,
        "bike_types": {k: b.label for k, b in BIKE_TYPES.items()},
        "avoid_types": {k: AVOID_TYPES[k][0] for k in BIKE_AVOID},
        "walk_available": s.walk_available,
        "walk_profiles": {k: {"label": p.label, "description": p.description, **p.weights()}
                          for k, p in config.WALK_PROFILES.items()},
        "walk_avoid_types": {k: AVOID_TYPES[k][0] for k in WALK_AVOID},
        "sources": getattr(s.region, "sources", {}),
    }


@app.get("/api/network")
def network(mode: str = "bike"):
    return state().walk_network if mode == "walk" else state().network


def _via(via: str | None) -> list[tuple[float, float]]:
    return [_latlon(p) for p in via.split(";") if p.strip()] if via else []


def _conditions(bike: str, depart: str | None, weather: bool, closures: bool,
                avoid: str | None = None, infra_only: bool = False, data: str = "all", reports: bool = True,
                mode: str = "bike"):
    try:
        ctx, info = state().live.context(bike, depart, weather, closures, reports)
    except ValueError as exc:
        raise HTTPException(400, f"Bad departure time: {exc}") from exc
    keys = {k for k in (avoid or "").split(",") if k}
    unknown = keys - set(WALK_AVOID if mode == "walk" else BIKE_AVOID)
    if unknown:
        raise HTTPException(400, f"Unknown avoid option(s): {', '.join(sorted(unknown))}")
    if data not in ("all", "osm"):
        raise HTTPException(400, "data must be 'all' or 'osm'")
    ctx.avoid, ctx.infra_only, ctx.osm_only = frozenset(keys), infra_only and mode == "bike", data == "osm"
    if mode == "walk":
        ctx.bike = "hybrid"          # bike type doesn't apply on foot
    info["notes"] = ctx.describe()
    return ctx, info


def _store(r, stats, info, title=None) -> dict:
    return state().store(r, stats, title) | {"conditions": info}


@app.get("/api/alternatives")
def alternatives(start: str, end: str, via: str | None = None, bike: str = "hybrid",
                 depart: str | None = None, weather: bool = True, closures: bool = True,
                 avoid: str | None = None, infra_only: bool = False,
                 data: str = "all", reports: bool = True, mode: str = "bike"):
    """Auto-generated options between two points (one per profile), each rated."""
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures, avoid, infra_only, data, reports, mode)
    routes = s.router_for(mode).alternatives(_latlon(start), _latlon(end), via=_via(via), ctx=ctx)
    fastest = min(r.time_s for r in routes)
    return [_store(r, rate(r, fastest_time_s=fastest), info) for r in routes]


@app.get("/api/route")
def route(start: str, end: str, profile: str = "balanced", via: str | None = None,
          bike: str = "hybrid", depart: str | None = None, weather: bool = True, closures: bool = True,
          avoid: str | None = None, infra_only: bool = False,
                 data: str = "all", reports: bool = True, mode: str = "bike", safety: float = 0, fun: float = 0, traffic: float = 0, hills: float = 0,
          surface: float = 0, shade: float = 0):
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures, avoid, infra_only, data, reports, mode)
    a, b, v = _latlon(start), _latlon(end), _via(via)
    rt = s.router_for(mode)
    if profile == "family" and mode == "bike":
        r = rt.family_route(a, b, v, ctx)
    else:
        r = rt.route(a, b, _profile(profile, safety, fun, traffic, hills, surface, shade), v, ctx)
    fastest = rt.route(a, b, "commute" if mode == "walk" else "fastest", v, ctx).time_s
    return _store(r, rate(r, fastest_time_s=fastest), info)


@app.get("/api/loop")
def loop(start: str, km: float = Query(15, ge=2, le=100), profile: str = "scenic",
         count: int = Query(3, ge=1, le=5), bike: str = "hybrid", depart: str | None = None,
         weather: bool = True, closures: bool = True, avoid: str | None = None, infra_only: bool = False,
                 data: str = "all", reports: bool = True, mode: str = "bike",
         safety: float = 0, fun: float = 0,
         traffic: float = 0, hills: float = 0, surface: float = 0, shade: float = 0):
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures, avoid, infra_only, data, reports, mode)
    loops = generate_loops(s.router_for(mode), _latlon(start), km,
                           _profile(profile, safety, fun, traffic, hills, surface, shade), count, ctx)
    return [_store(r, stats, info, f"{r.length_m / 1000:.1f} km loop") for r, stats in loops]


@app.get("/api/amenities")
def amenities():
    return state().amenities


@app.post("/api/extend/{rid}")
def extend(rid: str, body: dict = Body(...), bike: str = "hybrid", depart: str | None = None,
           weather: bool = True, closures: bool = True, avoid: str | None = None, infra_only: bool = False,
           data: str = "all", reports: bool = True):
    """Get to a route from a point, turn it into a loop, add stops and a final destination."""
    s = state()
    base, _, title = s.get(rid)
    mode = base.graph.graph.get("mode", "bike")
    ctx, info = _conditions(bike, depart, weather, closures, avoid, infra_only, data, reports, mode)
    pt = lambda v: tuple(float(x) for x in v) if v else None     # noqa: E731
    profile = body.get("profile") or base.profile
    if profile not in config.MODES[mode]:
        profile = "balanced"
    r = extend_route(s.router_for(mode), base, start=pt(body.get("start")), join=body.get("join", "start"),
                     after=body.get("after", "end"), stops=[pt(p) for p in body.get("stops", [])],
                     destination=pt(body.get("destination")), profile=profile, ctx=ctx)
    base_title = title or base.meta.get("title") or r.profile
    extra = [x for x in ("from your start" if body.get("start") else "",
                         "back to start" if body.get("after") == "return" else "",
                         "to your destination" if body.get("after") == "destination" else "") if x]
    return _store(r, rate(r), info, f"{base_title} ({', '.join(extra)})" if extra else base_title)


@app.post("/api/trip")
def trip(body: dict = Body(...), bike: str = "hybrid", depart: str | None = None, weather: bool = True,
         closures: bool = True, avoid: str | None = None, infra_only: bool = False, data: str = "all",
         reports: bool = True, mode: str = "bike"):
    """Trip builder: a route (A->B or loop) of a chosen length with chosen kinds of stops."""
    from cycleroutes.api.planning_api import _stop_features
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures, avoid, infra_only, data, reports, mode)
    pt = lambda v: tuple(float(x) for x in v) if v else None     # noqa: E731
    start, end = pt(body.get("start")), pt(body.get("end"))
    if start is None:
        raise HTTPException(400, "A start point is required")
    profile = body.get("profile") or ("balanced" if mode == "bike" else "balanced")
    if profile not in config.MODES[mode]:
        raise HTTPException(400, f"Unknown {mode} profile '{profile}'")
    target = float(body["target_km"]) if body.get("target_km") else None
    stops = [(x.get("type"), x.get("count", 1)) for x in body.get("stops", [])]
    unknown = [k for k, _ in stops if k not in STOP_TYPES]
    if unknown:
        raise HTTPException(400, f"Unknown stop type(s): {', '.join(unknown)}")
    results = plan_trip(s.router_for(mode), start, end, target, stops, _stop_features(), profile, ctx)
    out = []
    for route, placed in results:
        names = ", ".join(p["stop_label"].lower() for p in placed[:4])
        title = (f"{route.length_m / 1000:.0f} km {'loop' if end is None else 'trip'}"
                 + (f" via {names}" if names else ""))
        out.append(_store(route, rate(route), info, title))
    return out


@app.get("/api/stop-types")
def stop_types():
    return {k: label for k, (label, _) in STOP_TYPES.items()}


@app.get("/api/suggested")
def suggested(mode: str = "bike"):
    return state().walk_suggested if mode == "walk" else state().suggested


@app.get("/api/tour")
def tour(start: str, km: float = Query(5, ge=1, le=40), stops: int = Query(6, ge=2, le=12),
         loop: bool = True, mode: str = "walk", profile: str = "tourist", depart: str | None = None,
         weather: bool = True, closures: bool = True, avoid: str | None = None, data: str = "all",
         reports: bool = True):
    """Sightseeing tour through the best-rated sights near `start`."""
    from cycleroutes.data.sources import overture
    s = state()
    ctx, info = _conditions("hybrid", depart, weather, closures, avoid, False, data, reports, mode)
    rt = s.router_for(mode)
    prof = profile if profile in config.MODES[mode] else ("tourist" if mode == "walk" else "scenic")
    r, ordered = generate_tour(rt, _latlon(start), overture.load(s.region.name)["features"], km, stops, prof, loop, ctx)
    return _store(r, rate(r), info, r.meta["title"])


@app.get("/api/geocode")
def geocode(q: str):
    s = state()
    return [r.to_dict() for r in s.geocoder.search(q, viewbox=s.region.bbox)]


@app.get("/api/export/{rid}.gpx")
def export_gpx(rid: str):
    route_obj, stats, title = state().get(rid)
    name = title or "Cycle route"
    return Response(to_gpx(route_obj, name), media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="route-{rid}.gpx"'})


@app.get("/api/export/{rid}.pdf")
def export_pdf(rid: str, request: Request, basemap: str = "CyclOSM", layout: str = "standard",
               scale: int | None = Query(None, ge=2000, le=200000), qr: bool = True):
    route_obj, stats, title = state().get(rid)
    if layout not in ("standard", "strip", "card"):
        raise HTTPException(400, "layout must be standard, strip or card")
    qr_url = f"{str(request.base_url).rstrip('/')}/api/export/{rid}.gpx" if qr else None
    pdf = route_pdf(route_obj, stats, title or "Cycle route", basemap=basemap, layout=layout,
                    scale=scale, qr_url=qr_url)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="route-{rid}-{layout}.pdf"'})


@app.get("/sw.js")
def service_worker():
    """Served from the root so the offline cache covers the whole app."""
    return FileResponse(config.WEB_DIR / "sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
