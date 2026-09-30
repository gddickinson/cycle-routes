"""FastAPI backend + static web client.

Run:  uvicorn cycleroutes.api.app:app --reload     (region from $CYCLEROUTES_REGION)
"""

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cycleroutes import config
from cycleroutes.api.state import latlon as _latlon
from cycleroutes.api.state import state
from cycleroutes.api.community_api import router as community_router
from cycleroutes.api.planning_api import router as planning_router
from cycleroutes.api.tracking_api import router as tracking_router
from cycleroutes.export.formats import to_gpx
from cycleroutes.export.print_map import route_pdf
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.rating import rate
from cycleroutes.routing.context import BIKE_TYPES
from cycleroutes.routing.router import RoutingError, custom_profile

app = FastAPI(title="Cycle Routes prototype")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(tracking_router)
app.include_router(planning_router)
app.include_router(community_router)


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
        "sources": getattr(s.region, "sources", {}),
    }


@app.get("/api/network")
def network():
    return state().network


def _via(via: str | None) -> list[tuple[float, float]]:
    return [_latlon(p) for p in via.split(";") if p.strip()] if via else []


def _conditions(bike: str, depart: str | None, weather: bool, closures: bool):
    try:
        return state().live.context(bike, depart, weather, closures)
    except ValueError as exc:
        raise HTTPException(400, f"Bad departure time: {exc}") from exc


def _store(r, stats, info, title=None) -> dict:
    return state().store(r, stats, title) | {"conditions": info}


@app.get("/api/alternatives")
def alternatives(start: str, end: str, via: str | None = None, bike: str = "hybrid",
                 depart: str | None = None, weather: bool = True, closures: bool = True):
    """Auto-generated options between two points (one per profile), each rated."""
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures)
    routes = s.router.alternatives(_latlon(start), _latlon(end), via=_via(via), ctx=ctx)
    fastest = min(r.time_s for r in routes)
    return [_store(r, rate(r, fastest_time_s=fastest), info) for r in routes]


@app.get("/api/route")
def route(start: str, end: str, profile: str = config.DEFAULT_PROFILE, via: str | None = None,
          bike: str = "hybrid", depart: str | None = None, weather: bool = True, closures: bool = True,
          safety: float = 0, fun: float = 0, traffic: float = 0, hills: float = 0,
          surface: float = 0, shade: float = 0):
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures)
    a, b, v = _latlon(start), _latlon(end), _via(via)
    if profile == "family":
        r = s.router.family_route(a, b, v, ctx)
    else:
        r = s.router.route(a, b, _profile(profile, safety, fun, traffic, hills, surface, shade), v, ctx)
    fastest = s.router.route(a, b, "fastest", v, ctx).time_s
    return _store(r, rate(r, fastest_time_s=fastest), info)


@app.get("/api/loop")
def loop(start: str, km: float = Query(15, ge=2, le=100), profile: str = "scenic",
         count: int = Query(3, ge=1, le=5), bike: str = "hybrid", depart: str | None = None,
         weather: bool = True, closures: bool = True, safety: float = 0, fun: float = 0,
         traffic: float = 0, hills: float = 0, surface: float = 0, shade: float = 0):
    s = state()
    ctx, info = _conditions(bike, depart, weather, closures)
    loops = generate_loops(s.router, _latlon(start), km,
                           _profile(profile, safety, fun, traffic, hills, surface, shade), count, ctx)
    return [_store(r, stats, info, f"{r.length_m / 1000:.1f} km loop") for r, stats in loops]


@app.get("/api/amenities")
def amenities():
    return state().amenities


@app.get("/api/suggested")
def suggested():
    return state().suggested


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
