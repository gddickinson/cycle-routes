"""Trip builder: target lengths and chosen stops, for A->B trips and loops."""

import pytest

from cycleroutes.routing.planner import choose_stops, plan_trip
from cycleroutes.routing.router import Router

from conftest import LAT0, LON0, STEP, node_latlon


def _place(r, c, cat, name):
    return {"geometry": {"type": "Point", "coordinates": [LON0 + c * STEP, LAT0 + r * STEP + 0.0002]},
            "properties": {"category": cat, "name": name}}


FEATURES = [_place(0, 1, "cafe", "Bean There"), _place(0, 4, "cafe", "Far Café"),
            _place(0, 2, "water", "Fountain A"), _place(0, 3, "water", "Fountain B"),
            _place(3, 3, "park", "Parks Department Office"), _place(4, 2, "park", "Riverside Park")]


@pytest.fixture(scope="module")
def router(region):
    return Router(region.graph)


def test_stops_are_spread_and_filtered(region, router):
    base = router.route(node_latlon(region, 0, 0), node_latlon(region, 0, 5), "fastest")
    chosen = choose_stops(base, FEATURES, [("water", 2), ("cafe", 1)], 300)
    names = [c["name"] for c in chosen]
    assert names.count("Fountain A") == 1 and "Fountain B" in names          # two different water stops
    assert [c["at_km"] for c in chosen] == sorted(c["at_km"] for c in chosen)
    assert "Parks Department Office" not in [c["name"] for c in
                                             choose_stops(base, FEATURES, [("park", 1)], 2000)]


def test_trip_visits_chosen_stops(region, router):
    (route, stops), *_ = plan_trip(router, node_latlon(region, 0, 0), node_latlon(region, 0, 5), None,
                                   [("cafe", 1), ("water", 1)], FEATURES, "balanced")
    assert {s["stop_type"] for s in stops} == {"cafe", "water"}
    assert route.meta["planned_stops"] == stops and route.meta["missing_stops"] == []


def test_stretch_towards_target_length(region, router):
    a, b = node_latlon(region, 0, 0), node_latlon(region, 0, 2)
    direct = router.route(a, b, "balanced").length_m
    options = plan_trip(router, a, b, 2.5, [], [], "balanced")
    assert options[0][0].length_m > direct * 1.5
    assert abs(options[0][0].length_m - 2500) < abs(direct - 2500)


def test_loop_with_stops_and_missing_types(region, router):
    options = plan_trip(router, node_latlon(region, 2, 2), None, 3.0, [("park", 1), ("swim", 1)], FEATURES, "balanced")
    route, stops = options[0]
    assert route.kind == "loop" and route.nodes[0] == route.nodes[-1]
    assert route.meta["missing_stops"] == ["Swimming"]                       # none in the data: reported
