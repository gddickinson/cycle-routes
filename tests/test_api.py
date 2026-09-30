"""API tests against the synthetic region (PDF basemap tiles are stubbed)."""

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from cycleroutes.api import app as app_mod
from cycleroutes.api import live as live_mod
from cycleroutes.api import state as state_mod
from cycleroutes.export import tiles

from conftest import node_latlon


@pytest.fixture(scope="module")
def client(region, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(state_mod, "load_region", lambda name: region)
    mp.setattr(state_mod, "load_catalog", lambda r: [])
    mp.setattr(live_mod.weather, "at", lambda *a: None)   # keep tests offline
    mp.setattr(tiles.TileManager, "get_tile",
               lambda self, x, y, z: Image.new("RGB", (256, 256), (230, 235, 230)))
    state_mod.set_state(state_mod.AppState("test", rides_db=tmp_path_factory.mktemp("db") / "rides.sqlite"))
    yield TestClient(app_mod.app)
    state_mod.set_state(None)
    mp.undo()


def _ll(p):
    return f"{p[0]},{p[1]}"


def test_region(client):
    body = client.get("/api/region").json()
    assert body["name"] == "test" and "safest" in body["profiles"]


def test_alternatives_and_exports(client, region):
    a, b = _ll(node_latlon(region, 2, 0)), _ll(node_latlon(region, 2, 5))
    res = client.get(f"/api/alternatives?start={a}&end={b}")
    assert res.status_code == 200
    routes = res.json()
    assert routes and {"stats", "geojson", "cues", "elevation"} <= routes[0].keys()
    rid = routes[0]["id"]
    gpx = client.get(f"/api/export/{rid}.gpx")
    assert gpx.status_code == 200 and b"<gpx" in gpx.content
    pdf = client.get(f"/api/export/{rid}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_loop_and_errors(client, region):
    s = _ll(node_latlon(region, 2, 2))
    assert client.get(f"/api/loop?start={s}&km=3&profile=balanced&count=1").status_code == 200
    assert client.get("/api/route?start=31,-97&end=30,-97").status_code == 422
    assert client.get("/api/route?start=bad&end=30,-97").status_code == 400
    assert client.get("/api/export/nope.gpx").status_code == 404


def test_ride_recording_navigation_and_iphone_ingest(client, region):
    a, b = _ll(node_latlon(region, 0, 0)), _ll(node_latlon(region, 5, 5))
    planned = client.get(f"/api/route?start={a}&end={b}&profile=balanced").json()
    coords = [c for f in planned["geojson"]["features"] for c in f["geometry"]["coordinates"]]

    ride = client.post("/api/rides", json={"route_id": planned["id"]}).json()
    pts = [{"latitude": lat, "longitude": lon, "accuracy": 5, "timestamp": (1_700_000_000 + i * 40) * 1000}
           for i, (lon, lat) in enumerate(coords)]
    assert client.post(f"/api/rides/{ride['id']}/points", json={"points": pts}).json()["added"] == len(pts)

    mid = pts[len(pts) // 2]
    nav = client.post(f"/api/navigate/{planned['id']}", json=mid | {"restart": True}).json()
    assert 0 < nav["fraction"] < 1 and nav["next_cue"] and not nav["off_route"]

    done = client.post(f"/api/rides/{ride['id']}/finish").json()
    assert done["summary"]["distance_km"] > 1
    assert done["summary"]["on_network_pct"] > 90 and "safety" in done["summary"]["ratings"]
    assert done["matched"]["title"].startswith("Your ride")
    assert client.get(f"/api/rides/{ride['id']}.gpx").status_code == 200
    assert client.get(f"/api/rides/{ride['id']}.csv").text.startswith("time_utc")
    assert client.get(f"/api/rides/{ride['id']}").json()["track"]["geometry"]["coordinates"]

    live = client.get("/api/gps/live").json()
    assert live["source"] == "phone" and live["fix"]["latitude"] == pytest.approx(pts[-1]["latitude"])

    # pyNav / Pythonista iPhone tracker format
    packet = {"latitude": 30.001, "longitude": -96.999, "horizontal_accuracy": 8, "speed": 5.0,
              "course": 90, "timestamp": 1_700_000_100}
    res = client.post("/location", json={"locations": [packet], "source": "pythonista",
                                         "transmission_mode": "http"}).json()
    assert res["status"] == "success" and res["packets_received"] == 1
    again = client.post("/location", json={"locations": [packet], "source": "pythonista"}).json()
    assert again["ride_id"] == res["ride_id"]              # appended to the same open ride
    assert client.post("/location", json={"locations": []}).status_code == 400
    assert client.delete(f"/api/rides/{res['ride_id']}").json()["deleted"] == res["ride_id"]


def test_avoid_and_infra_params(client, region):
    a, b = _ll(node_latlon(region, 2, 0)), _ll(node_latlon(region, 2, 5))
    res = client.get(f"/api/route?start={a}&end={b}&profile=fastest&avoid=major,unpaved&infra_only=true")
    assert res.status_code == 200
    body = res.json()
    assert any("avoiding" in n for n in body["conditions"]["notes"])
    assert body["stats"]["avoided_km"] is not None
    assert client.get(f"/api/route?start={a}&end={b}&avoid=motorways").status_code == 400
    assert "avoid_types" in client.get("/api/region").json()
    trails = client.get("/api/layers/trails").json()
    assert trails["features"] and "paved" in trails["features"][0]["properties"]
