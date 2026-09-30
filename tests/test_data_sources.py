"""Extracts, the download cache, per-area settings, reuse of built areas, OSM-only scoring."""

import copy
import json

import numpy as np
import pytest

from cycleroutes import config
from cycleroutes.data import cache, extract, region as region_mod, settings
from cycleroutes.data.elevation import ElevationGrid
from cycleroutes.routing.context import RouteContext
from cycleroutes.routing.router import Router

from conftest import node_latlon


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cache, "ROOT", tmp_path / "sources")
    return tmp_path


def test_overpass_filter_parser_matches_osmnx_semantics():
    bike = extract.parse_filter('["highway"]["area"!~"yes"]["highway"!~"footway|motor|steps"]["bicycle"!~"no"]')
    assert bike({"highway": "residential"})
    assert not bike({"highway": "motorway_link"})          # "motor" matches as a substring, like Overpass
    assert not bike({"highway": "footway"})
    assert not bike({"highway": "residential", "bicycle": "no"})
    assert not bike({"building": "yes"})
    trail = extract.parse_filter(config.TRAIL_FILTERS[0])
    assert trail({"highway": "footway", "bicycle": "designated"})
    assert not trail({"highway": "footway", "bicycle": "yes", "footway": "sidewalk"})


def test_extract_registry_lookup():
    assert extract.extract_for(30.19, -97.84, 30.37, -97.64)["provider"] == "BBBike"
    assert extract.extract_for(51.3, -0.2, 51.6, 0.1) is None


def test_json_cache_reuses_covering_download(tmp_data):
    calls = []

    def fetch(b):
        calls.append(b)
        return [{"lat": 30.05, "lon": -97.05}, {"lat": 30.5, "lon": -97.5}]
    big, small = (30.0, -98.0, 31.0, -97.0), (30.0, -97.1, 30.1, -97.0)
    first = cache.json_source("crashes", big, fetch, cache.clip_points)
    second = cache.json_source("crashes", small, fetch, cache.clip_points)
    assert first.origin == "downloaded" and second.origin == "cached" and len(calls) == 1
    assert second.data == [{"lat": 30.05, "lon": -97.05}]                   # clipped to the small area
    third = cache.json_source("crashes", small, fetch, cache.clip_points, refresh=True)
    assert third.origin == "downloaded" and len(calls) == 2
    other = cache.json_source("crashes", (29.0, -98.0, 29.5, -97.5), fetch, cache.clip_points)
    assert other.origin == "downloaded"                                     # not covered


def test_array_cache_roundtrip(tmp_data):
    grid = ElevationGrid(np.ones((4, 4)) * 150, -98.0, 31.0, 0.25, 0.25)
    save = lambda g, p: cache.save_npz(p, data=g.data, meta=[g.west, g.north, g.res_x, g.res_y])  # noqa: E731
    cache.array_source("dem3dep", (30.0, -98.0, 31.0, -97.0), lambda b: grid, save, ElevationGrid.load)
    hit = cache.array_source("dem3dep", (30.2, -97.8, 30.4, -97.6), lambda b: 1 / 0, save, ElevationGrid.load)
    assert hit.origin == "cached" and float(hit.data.sample([-97.7], [30.3])[0]) == pytest.approx(150)
    assert any(d["source"] == "dem3dep" for d in cache.summary())


def test_settings_validate_and_merge(tmp_data):
    assert settings.load("x")["network"] == "auto"
    saved = settings.save("x", {"network": "extract", "layers": {"noise": False}})
    assert saved["network"] == "extract" and saved["layers"]["noise"] is False and saved["layers"]["canopy"]
    with pytest.raises(ValueError):
        settings.save("x", {"network": "carrier-pigeon"})
    with pytest.raises(ValueError):
        settings.save("x", {"layers": {"unicorns": True}})


def test_cut_from_already_built_area(tmp_data, region):
    parent = copy.deepcopy(region)
    parent.name = "parent"
    region_mod.save_region(parent)
    s, w, n, e = parent.bbox
    inner = (s + 0.001, w + 0.001, s + 0.0065, w + 0.0065)
    assert region_mod.find_covering_region(inner) == "parent"
    child = region_mod._cut_from(parent, "child", 30.0, -97.0, 300, inner)
    assert 0 < child.graph.number_of_nodes() < parent.graph.number_of_nodes()
    assert "cut from" in child.sources["network"]
    assert all("safety" in d for _, _, d in child.graph.edges(data=True))   # scores kept, nothing recomputed
    assert json.loads((tmp_data / "regions.json").read_text())["parent"]["bbox"]


def test_osm_only_scoring_ignores_extra_data(region):
    g = copy.deepcopy(region.graph)
    for _, _, d in g.edges(data=True):
        if d["highway"] == "residential" and d.get("name") == "Row 1":
            d["safety"] = 0.05          # pretend crash data condemned this street
    rt = Router(g)
    a, b = node_latlon(region, 1, 0), node_latlon(region, 1, 5)
    full = rt.route(a, b, "safest")
    osm = rt.route(a, b, "safest", ctx=RouteContext(osm_only=True))
    assert full.edge_set() != osm.edge_set()
    assert "OpenStreetMap only" in " ".join(RouteContext(osm_only=True).describe())
