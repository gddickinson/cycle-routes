"""Build a region from a downloaded OpenStreetMap extract (.osm.pbf) instead of Overpass.

City extracts (e.g. BBBike, updated weekly) download in seconds and avoid the busy
public Overpass servers. The *same* Overpass-style tag filters are applied here, so
both sources yield the same network: bike-legal streets + trails, scenic areas,
signed cycle-route relations and cyclist amenities.
"""

import logging
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

import geopandas as gpd
import networkx as nx
import osmium
import osmnx as ox
import requests
from shapely import wkb

from cycleroutes import config

logger = logging.getLogger(__name__)
FILTER_RE = re.compile(r'\["([^"]+)"(?:(!?[~=])"([^"]*)")?\]')


def parse_filter(text: str):
    """Overpass tag filter string -> predicate(tags dict)."""
    clauses = [(k, op, v) for k, op, v in FILTER_RE.findall(text)]

    def test(tags) -> bool:
        for key, op, val in clauses:
            present = key in tags
            cur = tags.get(key, "")
            if op == "":
                if not present:
                    return False
            elif op == "=":
                if cur != val:
                    return False
            elif op == "!=":
                if cur == val:
                    return False
            elif op == "~":
                if not present or not re.search(val, cur):
                    return False
            elif op == "!~":
                if present and re.search(val, cur):
                    return False
        return True
    return test


def extract_for(south: float, west: float, north: float, east: float) -> dict | None:
    """Registered extract whose coverage contains the bbox, or None."""
    for key, ex in config.EXTRACTS.items():
        s, w, n, e = ex["bbox"]
        if s <= south and n >= north and w <= west and e >= east:
            return {"key": key, **ex}
    return None


def local_path(ex: dict) -> Path:
    return config.DATA_DIR / "extracts" / Path(ex["url"]).name


def fetch_extract(ex: dict, refresh: bool = False) -> Path:
    """Download the extract once (cached under data_cache/extracts/)."""
    path = local_path(ex)
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s extract %s", ex["provider"], ex["url"])
    with requests.get(ex["url"], stream=True, timeout=600, headers={"User-Agent": config.USER_AGENT}) as r:
        r.raise_for_status()
        tmp = path.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    tmp.replace(path)
    return path


class _Collector(osmium.SimpleHandler):
    """One pass: network ways (with node locations), scenic areas, cycle routes, amenities."""

    def __init__(self, bbox, way_tests, scenic_test, amenity_category):
        super().__init__()
        s, w, n, e = bbox
        self.box = (s, w, n, e)
        self.way_tests = way_tests
        self.scenic_test, self.amenity_category = scenic_test, amenity_category
        self.ways, self.nodes = [], {}
        self.scenic, self.routes, self.amenities = [], {}, []
        self.wkb = osmium.geom.WKBFactory()

    def _inside(self, lat, lon) -> bool:
        s, w, n, e = self.box
        return s <= lat <= n and w <= lon <= e

    def node(self, n):
        cat = self.amenity_category(dict(n.tags)) if n.tags else None
        if cat and n.location.valid() and self._inside(n.location.lat, n.location.lon):
            self.amenities.append((n.location.lat, n.location.lon, cat, dict(n.tags)))

    def way(self, w):
        tags = dict(w.tags)
        if "highway" not in tags or not any(t(tags) for t in self.way_tests):
            return
        try:
            locs = [(nd.ref, nd.location.lat, nd.location.lon) for nd in w.nodes]
        except osmium.InvalidLocationError:
            return
        if not any(self._inside(lat, lon) for _, lat, lon in locs):
            return
        for ref, lat, lon in locs:
            self.nodes[ref] = (lat, lon)
        self.ways.append((w.id, [ref for ref, _, _ in locs], tags))

    def relation(self, r):
        tags = dict(r.tags)
        if tags.get("route") == "bicycle":
            name = tags.get("name") or tags.get("ref") or "Cycle route"
            rank = {"icn": 4, "ncn": 3, "rcn": 2, "lcn": 1}.get(tags.get("network", ""), 1)
            for m in r.members:
                if m.type == "w":
                    entry = self.routes.setdefault(m.ref, {"rank": 0, "names": []})
                    entry["rank"] = max(entry["rank"], rank)
                    if name not in entry["names"]:
                        entry["names"].append(name)

    def area(self, a):
        tags = dict(a.tags)
        if not self.scenic_test(tags):
            return
        try:
            geom = wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        c = geom.representative_point()
        s, w, n, e = self.box
        if geom.bounds[0] <= e and geom.bounds[2] >= w and geom.bounds[1] <= n and geom.bounds[3] >= s:
            self.scenic.append({**{k: tags.get(k) for k in ("name", "leisure", "natural", "landuse", "waterway",
                                                           "tourism")}, "geometry": geom, "_c": c})


def _scenic_test(tags) -> bool:
    return any(tags.get(k) in vals for k, vals in config.SCENIC_TAGS.items())


def _write_osm_xml(path: Path, nodes: dict, ways: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="cycleroutes">\n')
        for ref, (lat, lon) in nodes.items():
            fh.write(f'<node id="{ref}" lat="{lat:.7f}" lon="{lon:.7f}"/>\n')
        for wid, refs, tags in ways:
            fh.write(f'<way id="{wid}">')
            fh.write("".join(f'<nd ref="{r}"/>' for r in refs))
            fh.write("".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items()))
            fh.write("</way>\n")
        fh.write("</osm>\n")


def build_from_extract(path: Path, lat: float, lon: float, radius_m: float,
                       filters: list[str] | None = None, bidirectional: bool = False):
    """(graph, scenic features GeoDataFrame, cycle-route ways, amenity GeoJSON) for the area.

    filters default to the cycling network; pass walking filters (and bidirectional=True)
    for the pedestrian network.
    """
    from cycleroutes.data.amenities import CATEGORIES, _category
    from cycleroutes.data.osm_network import _configure_osmnx, bike_filters
    _configure_osmnx()
    west, south, east, north = ox.utils_geo.bbox_from_point((lat, lon), dist=radius_m)   # (left, bottom, right, top)
    bbox = (south, west, north, east)
    handler = _Collector(bbox, [parse_filter(f) for f in (filters or bike_filters())], _scenic_test, _category)
    logger.info("Reading %s", path.name)
    handler.apply_file(str(path), locations=True, idx="flex_mem")
    logger.info("Extract: %d ways, %d nodes, %d scenic areas, %d amenities",
                len(handler.ways), len(handler.nodes), len(handler.scenic), len(handler.amenities))

    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "network.osm"
        _write_osm_xml(xml, handler.nodes, handler.ways)
        graph = ox.graph_from_xml(xml, bidirectional=bidirectional, simplify=True, retain_all=True)
    graph = ox.truncate.truncate_graph_bbox(graph, (west, south, east, north), truncate_by_edge=False)
    graph = ox.truncate.largest_component(graph, strongly=False)
    logger.info("Network from extract: %d nodes, %d edges", graph.number_of_nodes(), graph.number_of_edges())

    scenic = gpd.GeoDataFrame([{k: v for k, v in s.items() if k != "_c"} for s in handler.scenic],
                              geometry="geometry", crs="EPSG:4326") if handler.scenic else \
        gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    amenities = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]},
         "properties": {k: v for k, v in {"category": cat, "label": CATEGORIES[cat][1], "name": t.get("name", ""),
                                          "opening_hours": t.get("opening_hours", ""),
                                          "capacity": t.get("capacity", ""), "fee": t.get("fee", "")}.items() if v}}
        for la, lo, cat, t in handler.amenities]}
    return nx.MultiDiGraph(graph), scenic, handler.routes, amenities
