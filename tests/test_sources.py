"""Open-data joins and data-aware scoring (offline: data is injected, not downloaded)."""

import copy

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from cycleroutes.data import enrich
from cycleroutes.data.sources import join, noise
from cycleroutes.data.sources.apply import AADT_CAP_BY_CLASS
from cycleroutes.scoring import edge_scores, lts

from conftest import LAT0, LON0, STEP


@pytest.fixture()
def reg(region):
    return copy.deepcopy(region)


def test_measured_traffic_raises_stress():
    street = {"highway": "residential", "maxspeed": "25 mph"}
    assert lts.effective(street) == 1
    assert lts.effective({"highway": "residential", "maxspeed": "30 mph"}) == 2
    assert lts.effective({**street, "aadt": 12000}) == 3
    assert lts.effective({**street, "aadt": 25000}) == 4
    assert lts.effective({**street, "aadt": 25000, "cycleway": "lane"}) == 3
    assert lts.effective({"highway": "cycleway", "aadt": 50000}) == 1


def test_city_comfort_blends_conservatively():
    assert lts.effective({"highway": "residential", "city_lts": 3}) == 2     # (1+3)/2
    assert lts.effective({"highway": "residential", "city_lts": 2}) == 2     # ties round up
    assert lts.effective({"highway": "cycleway", "city_lts": 1}) == 1


def test_crashes_lower_safety_and_traffic_quietness():
    base = {"highway": "residential", "lts": 1}
    assert edge_scores.safety({**base, "crashes": 3, "crashes_severe": 1}) < edge_scores.safety(base)
    assert edge_scores.quietness({**base, "aadt": 300}) > edge_scores.quietness({**base, "aadt": 20000})
    assert edge_scores.quietness({**base, "noise_db": 70}) < edge_scores.quietness({**base, "noise_db": 42})


def test_overlap_join_and_nearest(reg):
    edges = join.edges_frame(reg.graph)
    lane = gpd.GeoDataFrame({"city_lts": [1]}, geometry=[LineString(
        [(LON0, LAT0 + 2 * STEP), (LON0 + 5 * STEP, LAT0 + 2 * STEP)])], crs="EPSG:4326")
    matched = join.overlap_join(edges, lane)
    assert len(matched) == 5 and all(edges.loc[i, "hw"] == "primary" for i in matched)
    crash = [{"lat": LAT0 + 2 * STEP + 0.00005, "lon": LON0 + 0.5 * STEP}]
    hits = join.nearest_edges(edges, crash, 20)
    assert len(hits) == 1 and edges.loc[hits[0][0], "hw"] == "primary"


def test_propagate_by_name_spreads_along_street(reg):
    edges = join.edges_frame(reg.graph)
    seed = next(i for i, r in edges.iterrows() if r["name"] == "fast road")
    n = join.propagate_by_name(reg.graph, edges, {seed: 30000}, "aadt", max_m=450)
    assert 2 <= n <= 5
    assert all(d.get("aadt") in (None, 30000) for _, _, d in reg.graph.edges(data=True))
    assert not any(d.get("aadt") for _, _, d in reg.graph.edges(data=True) if d["highway"] != "primary")


def test_crossings_flagged_only_when_arriving_from_side_street(reg):
    enrich.add_scores(reg.graph)
    risky = [n for n, d in reg.graph.nodes(data=True) if d.get("risky_crossing")]
    assert risky, "junctions of calm streets with the LTS 4 road should be flagged"
    signals = [n for n, d in reg.graph.nodes(data=True) if d.get("highway") == "traffic_signals"]
    assert not any(reg.graph.nodes[n]["risky_crossing"] for n in signals)
    assert all(reg.graph.nodes[n]["busy_names"] == ("fast road",) for n in risky)


def test_aadt_caps_are_ordered():
    assert AADT_CAP_BY_CLASS["residential"] < AADT_CAP_BY_CLASS["tertiary"] < AADT_CAP_BY_CLASS["primary"]


def test_noise_legend_bands():
    assert noise._band_mid("45.0 - 49.9") == pytest.approx(47.45)
    assert noise._band_mid("> 90.0") == 92.5
