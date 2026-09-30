"""API tests against the synthetic region (PDF basemap tiles are stubbed)."""

import pytest


from conftest import node_latlon


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


def test_data_options_and_sources_api(client, region):
    a, b = _ll(node_latlon(region, 2, 0)), _ll(node_latlon(region, 2, 5))
    r = client.get(f"/api/route?start={a}&end={b}&data=osm&reports=false").json()
    assert any("OpenStreetMap only" in n for n in r["conditions"]["notes"])
    assert client.get(f"/api/route?start={a}&end={b}&data=bogus").status_code == 400
    s = client.get("/api/sources").json()
    assert s["network"]["options"]["overpass"] and s["layers"] and "downloads" in s
    assert client.post("/api/sources", json={"settings": {"network": "nope"}}).status_code == 400
    saved = client.post("/api/sources", json={"settings": {"layers": {"noise": False}}}).json()
    assert saved["settings"]["layers"]["noise"] is False
    from cycleroutes.data import settings as settings_mod
    settings_mod.path("test").unlink(missing_ok=True)      # leave no settings for the fake area behind


def test_walk_mode_api(client, region):
    import copy
    from cycleroutes.api import state as state_mod
    from cycleroutes.routing.router import Router
    from cycleroutes.scoring import walk_scores
    g = copy.deepcopy(region.graph)
    g.graph.update(mode="walk", base_kmh=4.8)
    for _, _, d in g.edges(data=True):
        walk_scores.score_edge(d)
    walk = copy.copy(region)
    walk.graph, walk.name = g, "test--walk"
    st = state_mod.state()
    st._walk = (walk, Router(g))
    a, b = _ll(node_latlon(region, 0, 0)), _ll(node_latlon(region, 5, 5))
    info = client.get("/api/region").json()
    assert info["walk_available"] and "tourist" in info["walk_profiles"] and "no_sidewalk" in info["walk_avoid_types"]
    alts = client.get(f"/api/alternatives?start={a}&end={b}&mode=walk").json()
    assert alts and all(r["mode"] == "walk" for r in alts) and "sidewalk_pct" in alts[0]["stats"]
    r = client.get(f"/api/route?start={a}&end={b}&mode=walk&profile=accessible&avoid=steps,no_sidewalk").json()
    assert r["profile_label"] == "Step-free"
    assert client.get(f"/api/route?start={a}&end={b}&mode=walk&avoid=major").status_code == 400
    assert client.get(f"/api/loop?start={a}&km=2&mode=walk&profile=green&count=1").status_code == 200
    assert client.get(f"/api/route?start={a}&end={b}&mode=boat").status_code == 400


def test_extend_and_saved_snapshot_api(client, region):
    a, b = _ll(node_latlon(region, 2, 2)), _ll(node_latlon(region, 2, 4))
    base = client.get(f"/api/route?start={a}&end={b}&profile=balanced").json()
    home = list(node_latlon(region, 0, 0))
    res = client.post(f"/api/extend/{base['id']}", json={"start": home, "after": "return"})
    assert res.status_code == 200
    r = res.json()
    assert [l["kind"] for l in r["legs"]] == ["approach", "route", "onward"] and r["kind"] == "loop"
    assert "back to start" in r["title"]
    assert client.post(f"/api/extend/{base['id']}", json={"after": "destination"}).status_code == 422
    fav = client.post("/api/favourites", json={"title": "Combined", "route_id": r["id"]}).json()
    opened = client.get(f"/api/favourites/{fav['id']}/route").json()
    assert opened["stats"]["distance_km"] == r["stats"]["distance_km"] and opened["title"] == "Combined"
    assert [l["kind"] for l in opened["legs"]] == ["approach", "route", "onward"]     # parts kept
    client.delete(f"/api/favourites/{fav['id']}")
