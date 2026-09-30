"""Build the walking network for an area (stored as region "<area>--walk").

Uses the same sources and download cache as cycling: the OSM extract (or Overpass)
with walking filters (sidewalks, footways, steps, pedestrian streets, shared paths,
all walkable both ways), elevation, shade, noise and measured traffic, plus walking-
specific data: pedestrian crashes and the city sidewalk inventory, and nearby cafés/
shops ("lively") and sights from Overture places.
"""

import logging
from collections import Counter

import networkx as nx
import osmnx as ox

from cycleroutes import config
from cycleroutes.data import cache, enrich, settings
from cycleroutes.data.region import Region, load_region, requested_bbox, save_region
from cycleroutes.data.sources import austin, join, overture
from cycleroutes.data.sources.apply import Ctx, apply_aadt, apply_canopy, apply_elevation, apply_noise
from cycleroutes.routing.geo import bearing_deg
from cycleroutes.scoring import walk_scores

logger = logging.getLogger(__name__)
LIVELY = {"cafe", "treat", "food", "shop"}
SIGHTS = {"landmark", "park", "swim"}


def walk_name(area: str) -> str:
    return f"{area}--walk"


def walk_filters() -> list[str]:
    from osmnx._overpass import _get_network_filter
    return [_get_network_filter("walk"), *config.WALK_EXTRA_FILTERS]


def _network(bike: Region, opts: dict, refresh: bool):
    from cycleroutes.data import extract
    bbox = requested_bbox(bike.lat, bike.lon, bike.radius_m)
    ex = extract.extract_for(*bbox)
    if opts["network"] in ("auto", "extract") and ex:
        path = extract.fetch_extract(ex, refresh=refresh)
        g, _, _, _ = extract.build_from_extract(path, bike.lat, bike.lon, bike.radius_m,
                                                filters=walk_filters(), bidirectional=True)
        return g, f"{ex['provider']} {ex['name']} extract (walking filters)"
    from cycleroutes.data import osm_network, overpass
    osm_network._configure_osmnx()
    g = overpass.with_fallback(lambda _url: ox.graph_from_point(
        (bike.lat, bike.lon), dist=bike.radius_m, dist_type="bbox", custom_filter=walk_filters(),
        simplify=True, retain_all=False))
    return ox.convert.to_undirected(g).to_directed(), "OpenStreetMap live (walking filters)"


def _apply_walk_data(region: Region, c: Ctx, edges) -> dict:
    report = {}
    g = region.graph
    if austin.covers(*c.bbox) and c.opts["layers"].get("crashes", True):
        hit = c.json("pedcrashes", austin.fetch_ped_crashes, cache.clip_points)
        counts: dict = {}
        for idx, crash in join.nearest_edges(edges, hit.data, config.CRASH_RADIUS_M):
            t = counts.setdefault(idx, [0, 0])
            t[0] += 1
            t[1] += int(crash["severe"])
        for idx, (n, sev) in counts.items():
            e = edges.loc[idx]
            join.set_both_directions(g, e["u"], e["v"], e["key"], ped_crashes=n, ped_crashes_severe=sev)
        austin.cache("pedcrashes", region.name, hit.data)
        report["crashes"] = f"{len(hit.data)} pedestrian crashes on {len(counts)} segments ({hit.describe()})"
    if austin.covers(*c.bbox) and c.opts["layers"].get("comfort", True):
        hit = c.json("sidewalks", austin.fetch_sidewalks, cache.clip_geojson)
        lines = join.geojson_frame(hit.data)
        n_yes = n_no = 0
        if not lines.empty:
            for want in (False, True):          # "exists" wins where both match
                sub = lines[lines["exists"] == want]
                if sub.empty:
                    continue
                for idx, row in join.overlap_join(edges, sub, buffer_m=14.0, min_overlap=0.4).items():
                    e = edges.loc[idx]
                    rating = row["rating"] if want and row["rating"] == row["rating"] else None
                    join.set_both_directions(g, e["u"], e["v"], e["key"], city_sidewalk=want,
                                             city_sidewalk_rating=int(rating) if rating else None)
                    n_yes, n_no = (n_yes + 1, n_no) if want else (n_yes, n_no + 1)
        report["sidewalks"] = f"{n_yes} segments with a city-mapped sidewalk, {n_no} without ({hit.describe()})"
    stops = overture.load(region.name.removesuffix("--walk"))["features"]
    pts = [{"lat": f["geometry"]["coordinates"][1], "lon": f["geometry"]["coordinates"][0],
            "cat": f["properties"]["category"]} for f in stops]
    lively = Counter(i for i, p in join.nearest_edges(edges, [p for p in pts if p["cat"] in LIVELY], 40.0))
    sights = Counter(i for i, p in join.nearest_edges(edges, [p for p in pts if p["cat"] in SIGHTS], 60.0))
    for idx in set(lively) | set(sights):
        e = edges.loc[idx]
        per_100m = lively.get(idx, 0) / max(e.geometry.length / 100, 0.5)
        join.set_both_directions(g, e["u"], e["v"], e["key"], lively=round(min(per_100m / 3, 1.0), 2),
                                 sights=1.0 if sights.get(idx) else 0.0)
    report["stops"] = f"{sum(lively.values())} cafés/shops and {sum(sights.values())} sights matched to streets"
    return report


def build_walk_region(area: str, refresh: bool = False) -> Region:
    bike = load_region(area)
    opts = settings.load(area)
    graph, network_desc = _network(bike, opts, refresh)
    graph = nx.MultiDiGraph(graph)
    graph.graph.update(mode="walk", base_kmh=config.WALK_BASE_KMH)
    region = Region(walk_name(area), bike.lat, bike.lon, bike.radius_m, graph, bike.features)
    edges_gdf = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True)[["geometry", "length"]]
    enrich.add_geometry(graph, edges_gdf)
    enrich.add_scenic_fraction(graph, edges_gdf, bike.features)
    for _, _, d in graph.edges(data=True):
        d.setdefault("route_rank", 0)
        d.setdefault("route_names", [])
    c = Ctx(region, refresh, opts)
    edges = join.edges_frame(graph)
    report = {"network": network_desc, "elevation": apply_elevation(c)}
    for name, step in (("canopy", apply_canopy), ("noise", apply_noise), ("aadt", apply_aadt)):
        report[name] = step(c, edges) if opts["layers"].get(name, True) else "switched off"
    report.update(_apply_walk_data(region, c, edges))
    for _, _, d in graph.edges(data=True):
        (x0, y0), (x1, y1) = d["geometry"].coords[0], d["geometry"].coords[-1]
        d["bearing"] = round(bearing_deg(y0, x0, y1, x1), 1)
        walk_scores.score_edge(d)
    enrich.add_crossings(graph)
    region.sources = report
    save_region(region)
    logger.info("Walking network: %d nodes, %d edges", graph.number_of_nodes(), graph.number_of_edges())
    return region
