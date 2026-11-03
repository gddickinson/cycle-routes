import pytest

from cycleroutes.export.formats import network_geojson, route_segments_geojson, to_gpx
from cycleroutes.routing.directions import cue_sheet
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.rating import rate
from cycleroutes.routing.router import Router, RoutingError, custom_profile

from conftest import node_latlon


@pytest.fixture(scope="module")
def router(region):
    return Router(region.graph)


def test_safest_avoids_fast_road(region, router):
    a, b = node_latlon(region, 2, 0), node_latlon(region, 2, 4)
    fastest = router.route(a, b, "fastest")
    safest = router.route(a, b, "safest")
    assert any(d["lts"] == 4 for d in fastest.edge_data())
    assert all(d["lts"] < 4 for d in safest.edge_data())
    assert safest.length_m >= fastest.length_m


def test_scenic_prefers_trail(region, router):
    a, b = node_latlon(region, 3, 0), node_latlon(region, 3, 5)
    scenic = router.route(a, b, "scenic")
    assert any(d["highway"] == "cycleway" for d in scenic.edge_data())


def test_flattest_avoids_hill_column(region, router):
    a, b = node_latlon(region, 0, 4), node_latlon(region, 5, 4)
    route = router.route(a, b, "flattest")
    assert rate(route)["ascent_m"] < 5


def test_alternatives_are_distinct_and_rated(region, router):
    a, b = node_latlon(region, 2, 0), node_latlon(region, 2, 5)
    routes = router.alternatives(a, b)
    assert 2 <= len(routes) <= 7
    fastest = min(r.time_s for r in routes)
    for r in routes:
        s = rate(r, fastest_time_s=fastest)
        assert all(0 <= v <= 10 for v in s["ratings"].values())
        assert abs(sum(s["lts_pct"].values()) - 100) < 0.5


def test_custom_profile(region, router):
    a, b = node_latlon(region, 2, 0), node_latlon(region, 2, 4)
    r = router.route(a, b, custom_profile(safety=5, traffic=5))
    assert all(d["lts"] < 4 for d in r.edge_data())


def test_snap_rejects_far_points(router):
    with pytest.raises(RoutingError):
        router.route((31.0, -97.0), (30.0, -97.0))


def test_loops(region, router):
    loops = generate_loops(router, node_latlon(region, 2, 2), 3.0, "balanced", count=2)
    assert loops
    route, stats = loops[0]
    assert route.nodes[0] == route.nodes[-1]
    assert stats["distance_error_pct"] < 60


def test_cues_and_exports(region, router):
    a, b = node_latlon(region, 0, 0), node_latlon(region, 5, 5)
    r = router.route(a, b, "balanced")
    cues = cue_sheet(r)
    assert cues[0].instruction.startswith("Start")
    assert cues[-1].instruction == "Arrive at destination"
    assert any("Turn" in c.instruction for c in cues)
    gpx = to_gpx(r, "Test & route")
    assert "<trkpt" in gpx and "&amp;" in gpx and "<ele>" in gpx
    assert "not checked by a person" in gpx          # safety notice travels with the file
    assert len(route_segments_geojson(r)["features"]) == len(r.edges)
    assert network_geojson(region.graph)["features"]
