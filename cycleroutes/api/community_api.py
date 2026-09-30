"""Community reports, street feedback, saved places/favourites, learned preferences
and live location sharing."""

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from cycleroutes import config
from cycleroutes.api.state import state
from cycleroutes.community.store import HAZARD_TYPES
from cycleroutes.data.sources import join
from cycleroutes.routing.directions import _street_name

router = APIRouter()


def _float(body: dict, key: str) -> float:
    try:
        return float(body[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"'{key}' is required") from exc


@router.get("/api/hazard-types")
def hazard_types():
    return {k: {"label": v[0], "days": v[2]} for k, v in HAZARD_TYPES.items()}


@router.get("/api/hazards")
def hazards():
    return state().community.hazards()


@router.post("/api/hazards")
def report(body: dict = Body(...)):
    lat, lon = _float(body, "lat"), _float(body, "lon")
    s = state()
    s.router.snap(lat, lon)            # must be on the mapped network
    try:
        hid = s.community.report_hazard(body.get("kind", "other"), lat, lon, body.get("note", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": hid, "message": "Thanks - routes will steer around it until it expires."}


@router.post("/api/hazards/{hazard_id}/{action}")
def hazard_action(hazard_id: int, action: str):
    store = state().community
    if action == "confirm":
        store.confirm_hazard(hazard_id)
    elif action == "resolve":
        store.resolve_hazard(hazard_id)
    else:
        raise HTTPException(404, "Use confirm or resolve")
    return {"ok": True}


@router.post("/api/feedback")
def feedback(body: dict = Body(...)):
    """Thumbs up/down on the street nearest to a point."""
    s = state()
    lat, lon = _float(body, "lat"), _float(body, "lon")
    hits = join.nearest_edges(s.live.edges, [{"lat": lat, "lon": lon}], 30.0)
    if not hits:
        raise HTTPException(422, "No street within 30 m of that point")
    row = s.live.edges.loc[hits[0][0]]
    s.community.rate_street(int(row["u"]), int(row["v"]), int(body.get("score", 1)))
    d = s.region.graph.edges[row["u"], row["v"], row["key"]]
    return {"street": _street_name(d), "score": 1 if int(body.get("score", 1)) > 0 else -1}


@router.get("/api/places")
def places():
    return state().community.places()


@router.post("/api/places")
def add_place(body: dict = Body(...)):
    return {"id": state().community.add_place(body.get("name") or "Place", _float(body, "lat"), _float(body, "lon"))}


@router.get("/api/favourites")
def favourites():
    return state().community.favourites()


@router.post("/api/favourites")
def add_favourite(body: dict = Body(...)):
    if not body.get("params"):
        raise HTTPException(400, "'params' (the route request) is required")
    return {"id": state().community.add_favourite(body.get("title") or "Favourite route", body["params"])}


@router.delete("/api/{table}/{row_id}")
def delete(table: str, row_id: int):
    if table not in ("places", "favourites"):
        raise HTTPException(404, "Unknown collection")
    if not state().community.delete(table, row_id):
        raise HTTPException(404, "Not found")
    return {"deleted": row_id}


@router.get("/api/profiles/learned")
def learned():
    return state().community.learned_weights() or {}


# --- live sharing -------------------------------------------------------------------
@router.post("/api/rides/{ride_id}/share")
def share_ride(ride_id: int, hours: float = 6):
    if not state().rides.ride(ride_id):
        raise HTTPException(404, "No such ride")
    token = state().community.create_share(ride_id, hours)
    return {"token": token, "path": f"/share/{token}", "hours": hours}


@router.get("/api/share/{token}")
def shared(token: str):
    s = state()
    share = s.community.share(token)
    if not share:
        raise HTTPException(404, "This link has expired")
    ride = s.rides.ride(share["ride_id"])
    points = s.rides.points(share["ride_id"])[-300:]
    route = None
    if ride and ride.get("route_id") and ride["route_id"] in s.routes:
        from cycleroutes.export.formats import route_segments_geojson
        route = route_segments_geojson(s.routes[ride["route_id"]][0])
    return {"name": ride["name"] if ride else "Ride", "finished": bool(ride and ride["ended"]),
            "points": [[p["lat"], p["lon"], p["t"]] for p in points], "route": route,
            "expires": share["expires"]}


@router.get("/share/{token}")
def share_page(token: str):
    return FileResponse(config.WEB_DIR / "share.html")
