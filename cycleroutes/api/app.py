"""FastAPI backend + static web client.

Run:  uvicorn cycleroutes.api.app:app --reload     (region from $CYCLEROUTES_REGION)
"""

from fastapi import FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cycleroutes import config
from cycleroutes.api.state import latlon as _latlon
from cycleroutes.api.state import state
from cycleroutes.api.tracking_api import router as tracking_router
from cycleroutes.export.formats import to_gpx
from cycleroutes.export.print_map import route_pdf
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.rating import rate
from cycleroutes.routing.router import RoutingError, custom_profile

app = FastAPI(title="Cycle Routes prototype")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.include_router(tracking_router)


def _profile(profile: str, safety, fun, traffic, hills, surface):
    if profile != "custom":
        return profile
    return custom_profile(safety=safety, fun=fun, traffic=traffic, hills=hills, surface=surface)


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
    }


@app.get("/api/network")
def network():
    return state().network


@app.get("/api/alternatives")
def alternatives(start: str, end: str):
    """Auto-generated options between two points (one per profile), each rated."""
    s = state()
    routes = s.router.alternatives(_latlon(start), _latlon(end))
    fastest = min(r.time_s for r in routes)
    return [s.store(r, rate(r, fastest_time_s=fastest)) for r in routes]


@app.get("/api/route")
def route(start: str, end: str, profile: str = config.DEFAULT_PROFILE,
          safety: float = 0, fun: float = 0, traffic: float = 0, hills: float = 0,
          surface: float = 0):
    s = state()
    r = s.router.route(_latlon(start), _latlon(end),
                       _profile(profile, safety, fun, traffic, hills, surface))
    fastest = s.router.route(_latlon(start), _latlon(end), "fastest").time_s
    return s.store(r, rate(r, fastest_time_s=fastest))


@app.get("/api/loop")
def loop(start: str, km: float = Query(15, ge=2, le=100), profile: str = "scenic",
         count: int = Query(3, ge=1, le=5), safety: float = 0, fun: float = 0,
         traffic: float = 0, hills: float = 0, surface: float = 0):
    s = state()
    loops = generate_loops(s.router, _latlon(start), km,
                           _profile(profile, safety, fun, traffic, hills, surface), count)
    return [s.store(r, stats, f"{r.length_m / 1000:.1f} km loop") for r, stats in loops]


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
def export_pdf(rid: str, basemap: str = "CyclOSM"):
    route_obj, stats, title = state().get(rid)
    pdf = route_pdf(route_obj, stats, title or "Cycle route", basemap=basemap)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="route-{rid}.pdf"'})


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
