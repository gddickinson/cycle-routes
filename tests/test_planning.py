"""Context-aware routing, via points, family cap, stops, stages, score, community store."""

import copy
from datetime import date, timezone

import pytest

from cycleroutes.community.store import CommunityStore
from cycleroutes.routing import stages, stops
from cycleroutes.routing.context import RouteContext, headwind_kmh, travel_time_s
from cycleroutes.routing.network_score import low_stress_score
from cycleroutes.routing.rating import rate
from cycleroutes.routing.router import Router
from cycleroutes.services.sun import sun_times

from conftest import node_latlon


@pytest.fixture(scope="module")
def router(region):
    return Router(region.graph)


def test_via_point_forces_detour(region, router):
    a, b = node_latlon(region, 0, 0), node_latlon(region, 0, 5)
    direct = router.route(a, b, "balanced")
    via = router.route(a, b, "balanced", via=[node_latlon(region, 4, 2)])
    assert via.length_m > direct.length_m + 1000
    assert via.meta["via"]


def test_bike_types_and_wind_change_time(region, router):
    a, b = node_latlon(region, 1, 0), node_latlon(region, 1, 5)
    hybrid = router.route(a, b, "fastest")
    ebike = router.route(a, b, "fastest", ctx=RouteContext(bike="ebike"))
    kids = router.route(a, b, "fastest", ctx=RouteContext(bike="kids"))
    assert ebike.time_s < hybrid.time_s < kids.time_s
    east = next(d for _, _, d in region.graph.edges(data=True) if 80 < d.get("bearing", 0) < 100)
    assert headwind_kmh(east, RouteContext(wind_kmh=20, wind_from_deg=90)) == pytest.approx(20, abs=1)
    assert travel_time_s(east, RouteContext(wind_kmh=20, wind_from_deg=90)) > \
        travel_time_s(east, RouteContext(wind_kmh=20, wind_from_deg=270))


def test_closures_and_reports_are_avoided(region, router):
    a, b = node_latlon(region, 3, 0), node_latlon(region, 3, 5)
    normal = router.route(a, b, "balanced")
    keys = normal.edge_set()
    closed = router.route(a, b, "balanced", ctx=RouteContext(closed=keys))
    assert not (closed.edge_set() & keys) or closed.length_m > normal.length_m
    report = router.route(a, b, "balanced", ctx=RouteContext(edge_multipliers={k: 50.0 for k in keys}))
    assert report.edge_set() != keys


def test_family_detour_cap(region, router):
    a, b = node_latlon(region, 1, 2), node_latlon(region, 3, 2)   # crossing the LTS 4 road is unavoidable
    fam = router.family_route(a, b)
    assert fam.length_m < 3000


def test_rating_reports_open_data(region, router):
    g = copy.deepcopy(region.graph)
    for _, _, d in g.edges(data=True):
        if d["highway"] == "primary":
            d.update(crashes=2, crashes_severe=1, aadt=30000, noise_db=65.0)
    r = Router(g).route(node_latlon(region, 2, 0), node_latlon(region, 2, 5), "fastest")
    s = rate(r)
    assert s["crashes"] >= 2 and s["busiest_aadt"] == 30000 and s["avg_noise_db"] > 45


def test_stops_along_and_stages(region, router):
    route = router.route(node_latlon(region, 0, 0), node_latlon(region, 5, 5), "balanced")
    lon, lat = route.coords()[1]
    feats = [{"geometry": {"type": "Point", "coordinates": [lon, lat + 0.0003]},
              "properties": {"category": "water", "name": "Fountain"}},
             {"geometry": {"type": "Point", "coordinates": [lon + 0.05, lat]},
              "properties": {"category": "cafe", "name": "Far away"}}]
    found = stops.along(route, feats)
    assert [s["name"] for s in found] == ["Fountain"] and found[0]["group"] == "water"
    assert stops.longest_dry_stretch(route, found) < route.length_m / 1000
    days = stages.split_stages(route, 0.8, [])
    assert len(days) >= 2 and sum(d["km"] for d in days) == pytest.approx(route.length_m / 1000, abs=0.05)


def test_network_score(region):
    s = low_stress_score(region.graph, samples=5)
    assert 0 <= s["score"] <= 100 and s["network_km"] > 0


def test_sun_times_austin():
    rise, set_ = sun_times(date(2026, 9, 29), 30.29, -97.74, timezone.utc)
    assert (rise.hour, set_.hour) == (12, 0)        # 07:2x and 19:2x Central = 12:xx / 00:xx UTC


def test_community_store(tmp_path):
    store = CommunityStore(tmp_path / "c.sqlite")
    hid = store.report_hazard("glass", 30.0, -97.0, "shards")
    assert store.hazards()[0]["label"] == "Glass or debris"
    store.confirm_hazard(hid)
    assert store.hazards()[0]["confirmations"] == 1
    store.resolve_hazard(hid)
    assert store.hazards() == []
    store.rate_street(5, 2, 1)
    store.rate_street(2, 5, 1)
    assert store.street_scores() == {(2, 5): 2}
    assert store.learned_weights() is None
    for _ in range(3):
        store.record_choice("safest", {"safety": 4, "fun": 0})
    assert store.learned_weights()["safety"] == 4
    token = store.create_share(1)
    assert store.share(token)["ride_id"] == 1
    with pytest.raises(ValueError):
        store.report_hazard("dragons", 0, 0)
