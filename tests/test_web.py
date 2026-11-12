"""Web interface tests: every exported endpoint answers, the static build is complete, and the JS engine tests pass.

Run: python -m pytest -q tests/test_web.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cycleroutes.web.app import STATIC, STATIC_ENDPOINTS, app  # noqa: E402

client = TestClient(app)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "static/main.js" in r.text


@pytest.mark.parametrize("path", STATIC_ENDPOINTS)
def test_endpoint(path):
    r = client.get("/api" + path)
    assert r.status_code == 200, r.text
    assert r.json() is not None


def test_static_build(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_static
    build_static.build(tmp_path / "site")
    assert (tmp_path / "site" / "index.html").read_text().count("APP_STATIC") == 1
    for path in STATIC_ENDPOINTS:
        assert (tmp_path / "site" / "api" / (path.strip("/") + ".json")).exists()


def test_static_assets_referenced_exist():
    html = (STATIC / "index.html").read_text()
    for name in ("style.css", "main.js"):
        assert f"static/{name}" in html and (STATIC / name).exists()


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_engine():
    tests = sorted(STATIC.glob("*.test.mjs"))
    for t in tests:
        r = subprocess.run(["node", str(t)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


# --- Cycle Routes specifics ----------------------------------------------------------------------------------------
import json  # noqa: E402

from cycleroutes.web import demo_area, examples  # noqa: E402


def _close(a, b, path=""):
    """Numbers within rtol 1e-9 (libm differs between macOS and Linux), everything else equal."""
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys(), path
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        assert a == pytest.approx(b, rel=1e-9, abs=1e-9), path
    else:
        assert a == b, path


def test_demo_graph_is_scored():
    g = demo_area.load_graph()
    assert g.number_of_edges() > 1000
    lts = {d["lts"] for _, _, d in g.edges(data=True)}
    assert lts <= {1, 2, 3, 4} and len(lts) >= 3
    s = demo_area.summary()
    assert s["network_km"] > 20 and abs(sum(s["lts_km"].values()) - s["network_km"]) < 0.5


def test_info_and_model():
    info = client.get("/api/info").json()
    assert "OpenStreetMap" in json.dumps(info["area"]["sources"]) and info["profiles"] >= 10
    m = client.get("/api/model").json()
    assert m["profiles"]["family"]["lts_penalty"] == {"3": 6.0, "4": 30.0}
    assert set(m["avoid_types"]) >= {"major", "busy", "unpaved"}


def test_examples_are_rated_routes():
    ex = client.get("/api/examples").json()
    assert ex["journeys"] and ex["loops"]
    for j in ex["journeys"]:
        assert len(j["routes"]) >= 2
        for r in j["routes"]:
            assert r["edges"] and 0 <= r["stats"]["ratings"]["overall"] <= 10 and r["cues"][-1]["instruction"].startswith("Arrive")
    assert all(r["kind"] == "loop" for r in ex["loops"])


def test_python_route_endpoint_matches_examples():
    j = examples.examples()["journeys"][0]
    got = client.post("/api/route", json={"start": j["start"], "end": j["end"]}).json()
    assert [r["edges"] for r in got] == [r["edges"] for r in j["routes"]]


def test_python_endpoints_validate():
    j = examples.examples()["journeys"][0]
    assert client.post("/api/route", json={"start": j["start"], "end": j["end"], "avoid": ["nope"]}).status_code == 400
    assert client.post("/api/route", json={"start": [0, 0], "end": j["end"]}).status_code == 422   # off the map
    assert client.post("/api/loop", json={"start": j["start"], "km": 500}).status_code == 400
    loops = client.post("/api/loop", json={"start": j["start"], "km": 3, "profile": "family", "count": 2}).json()
    assert 1 <= len(loops) <= 2


def test_python_score():
    busy = client.post("/api/score", json={"tags": {"highway": "primary", "lanes": "4", "maxspeed": "45 mph"}}).json()
    calm = client.post("/api/score", json={"tags": {"highway": "cycleway"}, "length": 300}).json()
    assert busy["lts"] == 4 and calm["lts"] == 1 and calm["safety"] > busy["safety"]
    measured = client.post("/api/score", json={"tags": {"highway": "residential"}, "aadt": 25000}).json()
    assert measured["lts"] == 4 and measured["lts_osm"] == 1


def test_areas_lists_built_regions():
    r = client.get("/api/areas").json()
    assert isinstance(r["areas"], list)


def test_engine_fixture_is_current():
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_engine_fixtures
    saved = json.loads(make_engine_fixtures.FIXTURE.read_text())
    _close(json.loads(json.dumps(make_engine_fixtures.build_fixture())), saved)
