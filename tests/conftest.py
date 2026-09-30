"""Offline fixtures: a small synthetic scored street grid (no network access)."""

import geopandas as gpd
import networkx as nx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from shapely.geometry import LineString

from cycleroutes.api import app as app_mod
from cycleroutes.api import live as live_mod
from cycleroutes.api import state as state_mod
from cycleroutes.data import enrich
from cycleroutes.data.elevation import ElevationGrid
from cycleroutes.data.region import Region
from cycleroutes.export import tiles

LAT0, LON0 = 30.0, -97.0
STEP = 0.002  # ~200 m
N = 6


def _street(r: int, c: int, horizontal: bool) -> dict:
    """Tags for the street leaving grid cell (r, c)."""
    if horizontal and r == 2:
        return {"highway": "primary", "lanes": "4", "maxspeed": "45 mph", "name": "Fast Road"}
    if horizontal and r == 4:
        return {"highway": "cycleway", "name": "River Trail", "surface": "asphalt"}
    if not horizontal and c == 5:
        return {"highway": "residential", "name": "Hill Street"}
    return {"highway": "residential", "name": f"{'Row' if horizontal else 'Col'} {r if horizontal else c}"}


def make_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph(crs="EPSG:4326")
    nid = lambda r, c: r * N + c  # noqa: E731
    for r in range(N):
        for c in range(N):
            g.add_node(nid(r, c), y=LAT0 + r * STEP, x=LON0 + c * STEP)
    g.nodes[nid(2, 2)]["highway"] = "traffic_signals"
    osmid = 1
    for r in range(N):
        for c in range(N):
            for dr, dc, horiz in ((0, 1, True), (1, 0, False)):
                r2, c2 = r + dr, c + dc
                if r2 >= N or c2 >= N:
                    continue
                a, b = nid(r, c), nid(r2, c2)
                tags = _street(r, c, horiz)
                for u, v in ((a, b), (b, a)):
                    pu, pv = g.nodes[u], g.nodes[v]
                    geom = LineString([(pu["x"], pu["y"]), (pv["x"], pv["y"])])
                    g.add_edge(u, v, osmid=osmid, length=200.0, geometry=geom, **tags)
                osmid += 1
    return g


def make_grid() -> ElevationGrid:
    """Terrain rising 30 m per 0.002 deg eastwards over the last column."""
    cols = np.linspace(LON0 - 0.01, LON0 + 0.02, 61)
    rows = np.linspace(LAT0 + 0.02, LAT0 - 0.01, 61)
    lon_grid, _ = np.meshgrid(cols, rows)
    data = np.where(lon_grid > LON0 + 4 * STEP, (lon_grid - (LON0 + 4 * STEP)) / STEP * 30, 0.0) + 100
    return ElevationGrid(data, LON0 - 0.01 - 0.00025, LAT0 + 0.02 + 0.00025, 0.0005, 0.0005)


@pytest.fixture(scope="session")
def region() -> Region:
    g = make_graph()
    park = gpd.GeoDataFrame({"name": ["Riverside Park"], "leisure": ["park"]},
                            geometry=[LineString([(LON0, LAT0 + 4 * STEP),
                                                  (LON0 + 5 * STEP, LAT0 + 4 * STEP)]).buffer(0.0003)],
                            crs="EPSG:4326")
    route_ways = {osmid: {"rank": 1, "names": ["Test Loop"]}
                  for _, _, d in g.edges(data=True) if d["highway"] == "cycleway"
                  for osmid in [d["osmid"]]}
    edges = gpd.GeoDataFrame(
        [{"u": u, "v": v, "key": k, "geometry": d["geometry"], "length": d["length"]}
         for u, v, k, d in g.edges(keys=True, data=True)], crs="EPSG:4326"
    ).set_index(["u", "v", "key"])
    enrich.add_scenic_fraction(g, edges, park)
    enrich.add_elevation(g, make_grid())
    enrich.add_cycle_routes(g, route_ways)
    enrich.add_scores(g)
    return Region("test", LAT0 + 2.5 * STEP, LON0 + 2.5 * STEP, 800, g, park)


def node_latlon(region: Region, r: int, c: int) -> tuple[float, float]:
    d = region.graph.nodes[r * N + c]
    return d["y"], d["x"]


@pytest.fixture(scope="session")
def client(region, tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(state_mod, "load_region", lambda name: region)
    mp.setattr(state_mod, "load_catalog", lambda r: [])
    mp.setattr(live_mod.weather, "at", lambda *a: None)   # keep tests offline
    mp.setattr(tiles.TileManager, "get_tile",
               lambda self, x, y, z: Image.new("RGB", (256, 256), (230, 235, 230)))
    state_mod.set_state(state_mod.AppState("test", rides_db=tmp_path_factory.mktemp("db") / "rides.sqlite"))
    yield TestClient(app_mod.app)
    state_mod.set_state(None)
    mp.undo()
