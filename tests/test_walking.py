"""Walking: pedestrian stress, walking scores, trip types, tours, API in walk mode."""

import copy

import pytest

from cycleroutes.data import enrich
from cycleroutes.routing.rating import rate
from cycleroutes.routing.router import Router, RoutingError
from cycleroutes.routing.tours import generate_tour, order_stops, pick_sights
from cycleroutes.scoring import walk_scores

from conftest import LAT0, LON0, STEP, node_latlon


@pytest.fixture(scope="module")
def walk_graph(region):
    g = copy.deepcopy(region.graph)
    g.graph.update(mode="walk", base_kmh=4.8)
    for u, v, d in g.edges(data=True):
        if d["highway"] == "residential" and d.get("name") == "Col 3":
            d["highway"] = "steps"
        if d["highway"] == "primary":
            d["sidewalk"] = "no"
        walk_scores.score_edge(d)
    enrich.add_crossings(g)
    return g


def test_pedestrian_stress_levels():
    assert walk_scores.pedestrian_stress({"highway": "footway"}) == 1
    assert walk_scores.pedestrian_stress({"highway": "residential", "maxspeed": "25 mph"}) == 1
    assert walk_scores.pedestrian_stress({"highway": "secondary", "sidewalk": "both", "maxspeed": "30 mph"}) == 2
    assert walk_scores.pedestrian_stress({"highway": "primary", "sidewalk": "no", "maxspeed": "45 mph"}) == 4
    assert walk_scores.has_sidewalk({"highway": "tertiary"}) is None           # unknown, not "absent"
    assert walk_scores.has_sidewalk({"highway": "tertiary", "city_sidewalk": False}) is False


def test_walking_speed_and_access():
    flat = {"highway": "footway", "length": 100.0}
    up = {**flat, "ascent": 10.0}
    assert walk_scores.speed_kmh(flat) == pytest.approx(5.0, abs=0.05)
    assert walk_scores.speed_kmh(up) < walk_scores.speed_kmh(flat)
    assert not walk_scores.accessible({"highway": "steps", "length": 20.0})
    assert not walk_scores.accessible({"highway": "footway", "length": 50.0, "ascent": 8.0})
    assert walk_scores.accessible({"highway": "footway", "length": 50.0, "ascent": 1.0})
    hike = {"highway": "path", "length": 500.0, "sac_scale": "demanding_mountain_hiking"}
    assert walk_scores.speed_kmh(hike) < walk_scores.speed_kmh({**hike, "sac_scale": "hiking"})


def test_walk_profiles_route(region, walk_graph):
    rt = Router(walk_graph)
    assert rt.mode == "walk"
    a, b = node_latlon(region, 0, 2), node_latlon(region, 5, 4)
    step_free = rt.route(a, b, "accessible")
    assert not any(d["highway"] == "steps" for d in step_free.edge_data())
    s = rate(step_free)
    assert s["mode"] == "walk" and s["accessible_pct"] > 90 and s["steps"] == 0
    safest = rt.route(node_latlon(region, 2, 0), node_latlon(region, 2, 5), "safest")
    assert not any(d["highway"] == "primary" for d in safest.edge_data())   # no sidewalk, LTS 4
    with pytest.raises(RoutingError):
        rt.route(a, b, "family")               # a cycling profile isn't a walking trip type


def test_tour_picks_orders_and_routes(region, walk_graph):
    feats = [{"geometry": {"type": "Point", "coordinates": [LON0 + c * STEP, LAT0 + r * STEP]},
              "properties": {"name": f"Sight {r}{c}", "category": "landmark", "confidence": 0.9}}
             for r, c in ((1, 1), (4, 1), (4, 4), (1, 4), (1, 1.05))]
    start = node_latlon(region, 0, 0)
    sights = pick_sights(feats, start, 2000, 6)
    assert len(sights) == 4                         # the near-duplicate (< 150 m apart) is dropped
    ordered = order_stops(start, sights, loop=True)
    assert ordered[0]["name"] == "Sight 11"          # nearest first
    route, stops = generate_tour(Router(walk_graph), start, feats, max_km=4, n_stops=4)
    assert route.kind == "loop" and route.nodes[0] == route.nodes[-1] and len(stops) >= 2
