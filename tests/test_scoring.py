from cycleroutes.data.elevation import climb_along
from cycleroutes.scoring import edge_scores, lts, tags


def test_speed_parsing():
    assert tags.parse_speed_kmh("30 mph") == 30 * 1.609
    assert tags.parse_speed_kmh("50") == 50
    assert tags.parse_speed_kmh("none") is None


def test_list_valued_tags_take_most_car_like_highway():
    assert tags.highway({"highway": ["residential", "primary"]}) == "primary"
    assert tags.highway({"highway": "secondary_link"}) == "secondary"


def test_lts_classification():
    assert lts.classify({"highway": "cycleway"}) == 1
    assert lts.classify({"highway": "residential"}) == 1
    assert lts.classify({"highway": "tertiary", "cycleway": "lane", "maxspeed": "30 mph"}) == 2
    assert lts.classify({"highway": "secondary", "maxspeed": "50"}) == 3
    assert lts.classify({"highway": "secondary", "maxspeed": "60"}) == 4
    assert lts.classify({"highway": "primary", "lanes": "4", "maxspeed": "45 mph"}) == 4
    assert lts.classify({"highway": "primary", "cycleway:right": "track"}) == 1


def test_surface_and_quietness():
    assert edge_scores.surface({"highway": "path", "surface": "gravel"}) < 0.5
    assert edge_scores.surface({"highway": "residential"}) == 1.0
    assert edge_scores.quietness({"highway": "cycleway"}) > edge_scores.quietness({"highway": "primary"})


def test_climb_ignores_small_noise():
    assert climb_along([100, 100.4, 100.1, 100.5]) == (0.0, 0.0)
    up, down = climb_along([100, 105, 103, 110])
    assert up == 12 and down == 2


def test_uphill_is_slower():
    flat = {"highway": "residential", "length": 200.0}
    hill = {**flat, "ascent": 20.0}
    assert edge_scores.travel_time_s(hill) > edge_scores.travel_time_s(flat)


def test_enriched_fixture(region):
    g = region.graph
    fast = [d for _, _, d in g.edges(data=True) if d["highway"] == "primary"]
    trail = [d for _, _, d in g.edges(data=True) if d["highway"] == "cycleway"]
    assert all(d["lts"] == 4 for d in fast)
    assert all(d["lts"] == 1 and d["route_rank"] == 1 for d in trail)
    assert max(d["scenic"] for d in trail) > 0.5
    assert max(d["ascent"] for _, _, d in g.edges(data=True)) > 20
