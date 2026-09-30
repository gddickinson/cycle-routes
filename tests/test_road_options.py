"""Avoiding road types, bike-lanes-only routing, cycle trails and MTB grades."""

import pytest

from cycleroutes.routing.context import AVOID_TYPES, RouteContext
from cycleroutes.routing.rating import rate
from cycleroutes.routing.router import Router
from cycleroutes.scoring import edge_scores, tags

from conftest import node_latlon


@pytest.fixture(scope="module")
def router(region):
    return Router(region.graph)


def test_trail_and_infra_detection():
    assert tags.is_trail({"highway": "path"})
    assert tags.is_trail({"highway": "footway", "bicycle": "yes"})
    assert not tags.is_trail({"highway": "footway", "footway": "sidewalk", "bicycle": "yes"})
    assert tags.is_trail({"highway": "cycleway", "name": "Shoal Creek Trail"})
    assert not tags.is_trail({"highway": "cycleway", "name": "Guadalupe Street"})
    assert tags.mtb_scale({"highway": "path", "mtb:scale": "2+"}) == 2
    assert tags.has_bike_infra({"highway": "tertiary", "cycleway:right": "lane"})
    assert tags.has_bike_infra({"highway": "residential", "city_facility": "Bike Lane - Buffered"})
    assert not tags.has_bike_infra({"highway": "residential", "city_facility": "Wide Curb Lane"})


def test_technical_trails_are_slow_and_rough():
    easy = {"highway": "path", "length": 500.0, "surface": "compacted"}
    hard = {**easy, "mtb:scale": "3"}
    assert edge_scores.speed_kmh(hard) < edge_scores.speed_kmh(easy)
    assert edge_scores.surface(hard) <= 0.3


def test_every_avoid_option_is_a_valid_predicate():
    edge = {"highway": "primary", "lts": 4, "surface_q": 1.0, "trail": False}
    assert AVOID_TYPES["major"][1](edge) and AVOID_TYPES["stressful"][1](edge)
    assert not AVOID_TYPES["trails"][1](edge)


def test_avoiding_major_roads(region, router):
    a, b = node_latlon(region, 2, 0), node_latlon(region, 2, 5)
    plain = router.route(a, b, "fastest")
    assert any(d["highway"] == "primary" for d in plain.edge_data())
    ctx = RouteContext(avoid=frozenset({"major"}))
    avoided = router.route(a, b, "fastest", ctx=ctx)
    assert not any(d["highway"] == "primary" for d in avoided.edge_data())
    assert rate(avoided)["avoided_km"] == 0


def test_avoid_is_soft_when_unavoidable(region, router):
    a, b = node_latlon(region, 1, 2), node_latlon(region, 3, 2)   # must cross the primary road
    ctx = RouteContext(avoid=frozenset({"major", "stressful"}))
    r = router.route(a, b, "balanced", ctx=ctx)      # still routes, just reports it
    assert r.length_m > 0


def test_bike_lanes_only_prefers_infrastructure(region, router):
    a, b = node_latlon(region, 4, 0), node_latlon(region, 4, 5)
    r = router.route(a, b, "fastest", ctx=RouteContext(infra_only=True))
    assert rate(r)["bike_infra_pct"] > 90


def test_trails_profile_uses_the_trail(region, router):
    a, b = node_latlon(region, 3, 0), node_latlon(region, 5, 5)
    r = router.route(a, b, "trails")
    assert rate(r)["trail_pct"] > 40


def test_protected_lane_on_major_road_is_not_avoided():
    protected = {"highway": "primary", "cycleway:right": "track", "lts": 1}
    painted = {"highway": "primary", "cycleway:right": "lane", "lts": 3}
    city = {"highway": "secondary", "city_facility": "Bike Lane - Protected One-Way", "lts": 2}
    assert not AVOID_TYPES["major"][1](protected)
    assert AVOID_TYPES["major"][1](painted)
    assert not AVOID_TYPES["secondary"][1](city)
