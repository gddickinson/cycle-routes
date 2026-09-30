"""Getting to a route, making it a loop, stops and destinations; saved-route snapshots."""

import pytest

from cycleroutes.export.formats import route_segments_geojson
from cycleroutes.routing.combine import extend_route, route_from_edges
from cycleroutes.routing.loops import generate_loops
from cycleroutes.routing.router import Router, RoutingError

from conftest import node_latlon


@pytest.fixture(scope="module")
def router(region):
    return Router(region.graph)


def test_get_there_then_return_makes_a_loop(region, router):
    base = router.route(node_latlon(region, 2, 2), node_latlon(region, 2, 4), "balanced")
    home = node_latlon(region, 0, 0)
    r = extend_route(router, base, start=home, after="return")
    kinds = [l["kind"] for l in r.meta["legs"]]
    assert kinds == ["approach", "route", "onward"]
    assert r.kind == "loop" and r.nodes[0] == r.nodes[-1] == router.snap(*home)
    core = r.meta["leg_bounds"]["route"]
    assert r.edges[core[0]:core[1]] == base.edges                  # the original route, unchanged
    legs = {f["properties"]["leg"] for f in route_segments_geojson(r)["features"]}
    assert legs == {"approach", "route", "onward"}


def test_join_a_loop_at_its_nearest_point(region, router):
    loop, _ = generate_loops(router, node_latlon(region, 2, 2), 3.0, "balanced", count=1)[0]
    near = node_latlon(region, 5, 5)
    r = extend_route(router, loop, start=near, join="nearest", after="return")
    base_len, approach = loop.length_m, r.meta["legs"][0]["km"] * 1000
    whole = extend_route(router, loop, start=near, join="start", after="return")
    assert r.length_m <= whole.length_m + 1                          # joining nearby is never longer
    assert approach < whole.meta["legs"][0]["km"] * 1000 + 1
    assert abs(sum(l["km"] for l in r.meta["legs"] if l["kind"] == "route") * 1000 - base_len) < 1


def test_stops_and_destination(region, router):
    base = router.route(node_latlon(region, 0, 0), node_latlon(region, 0, 3), "balanced")
    r = extend_route(router, base, after="destination", stops=[node_latlon(region, 3, 3)],
                     destination=node_latlon(region, 5, 0))
    assert r.nodes[-1] == router.snap(*node_latlon(region, 5, 0))
    assert router.snap(*node_latlon(region, 3, 3)) in r.nodes
    with pytest.raises(RoutingError):
        extend_route(router, base, after="destination")


def test_mode_mismatch_and_snapshot(region, router):
    base = router.route(node_latlon(region, 0, 0), node_latlon(region, 0, 3), "balanced")
    import copy
    other = Router(copy.deepcopy(region.graph))
    with pytest.raises(RoutingError):
        extend_route(other, base, start=node_latlon(region, 1, 1))
    again = route_from_edges(region.graph, [list(e) for e in base.edges], "balanced", "a_to_b", "Saved")
    assert again.edges == base.edges and again.meta["title"] == "Saved"
    with pytest.raises(RoutingError):
        route_from_edges(region.graph, [[1, 999, 0]], "balanced", "a_to_b")
