"""Apply every open data source that covers a region (and is switched on), then re-score.

Data already downloaded is reused through data/cache.py whenever it covers the area
(unless the area's settings say otherwise or refresh=True). Switching a layer off in
the settings removes its values from the graph. Each source is optional: failures are
logged and skipped.
"""

import json
import logging

import numpy as np
from affine import Affine
from pyproj import Transformer
from rasterio.crs import CRS

from cycleroutes import config
from cycleroutes.data import cache, enrich, settings
from cycleroutes.data.elevation import ElevationGrid, fetch_elevation_grid
from cycleroutes.data.region import Region
from cycleroutes.data.sources import austin, canopy, join, noise, overture, txdot_aadt, usgs_3dep

logger = logging.getLogger(__name__)

# Highest plausible daily traffic per street class; a count above this means the
# station belongs to a nearby bigger road (usually a freeway beside its frontage road).
AADT_CAP_BY_CLASS = {"living_street": 3000, "residential": 8000, "service": 8000, "unclassified": 15000,
                     "tertiary": 30000, "secondary": 50000, "primary": 90000, "road": 30000}
# graph attributes each optional layer writes (removed when the layer is switched off)
LAYER_ATTRS = {"canopy": ("shade",), "noise": ("noise_db",), "aadt": ("aadt",),
               "comfort": ("city_lts", "city_facility"), "crashes": ("crashes", "crashes_severe")}


class Ctx:
    """Per-run options shared by the apply_* steps."""

    def __init__(self, region: Region, refresh: bool, opts: dict):
        self.region, self.refresh, self.opts = region, refresh, opts
        self.prefer_cached = opts["prefer_cached"]
        # Cache key: the area as requested (lat/lon/radius) grown to cover the network, so the
        # cycling and walking networks of one area share the same downloads.
        from cycleroutes.data.region import requested_bbox
        rs, rw, rn, re_ = requested_bbox(region.lat, region.lon, region.radius_m)
        s, w, n, e = region.bbox
        self.bbox = (min(s, rs), min(w, rw), max(n, rn), max(e, re_))

    def json(self, source, fetch, clip=None) -> cache.Hit:
        return cache.json_source(source, self.bbox, fetch, clip, self.refresh, self.prefer_cached)

    def array(self, source, fetch, save, load) -> cache.Hit:
        return cache.array_source(source, self.bbox, fetch, save, load, self.refresh, self.prefer_cached)


# --- savers/loaders for raster-like sources -------------------------------------------
def _save_dem(g: ElevationGrid, p):
    cache.save_npz(p, data=g.data, meta=np.array([g.west, g.north, g.res_x, g.res_y]))


def _save_canopy(g, p):
    cache.save_npz(p, data=g.data, transform=np.array(list(g.transform)[:6]), crs=np.array(g.crs.to_string()))


def _load_canopy(p):
    f = np.load(p)
    return canopy.CanopyGrid(f["data"], Affine(*f["transform"]), CRS.from_string(str(f["crs"])))


def _save_noise(g, p):
    cache.save_npz(p, db=g.db, origin=np.array([g.px0, g.py0]))


def _load_noise(p):
    f = np.load(p)
    return noise.NoiseGrid(f["db"], float(f["origin"][0]), float(f["origin"][1]))


# --- steps ---------------------------------------------------------------------------
def apply_elevation(c: Ctx) -> str:
    choice = c.opts["elevation"]
    in_us = usgs_3dep.covers(*c.bbox)
    if choice == "3dep" and not in_us:
        return "skipped: USGS 3DEP only covers the US (choose Copernicus)"
    if choice == "3dep" or (choice == "auto" and in_us):
        hit = c.array("dem3dep", lambda b: usgs_3dep.fetch_3dep_grid(*b), _save_dem, ElevationGrid.load)
        label = "USGS 3DEP bare earth"
    else:
        hit = c.array("dem_copernicus", lambda b: fetch_elevation_grid(*b), _save_dem, ElevationGrid.load)
        label = "Copernicus GLO-30 (buildings filtered)"
    enrich.add_elevation(c.region.graph, hit.data)
    return f"{label} ({hit.describe()})"


def apply_city_comfort(c: Ctx, edges) -> str:
    hit = c.json("bikefacilities", austin.fetch_bike_facilities, cache.clip_geojson)
    lines = join.geojson_frame(hit.data)
    if lines.empty:
        return "no data"
    matched = join.overlap_join(edges, lines)
    for idx, row in matched.items():
        e = edges.loc[idx]
        join.set_both_directions(c.region.graph, e["u"], e["v"], e["key"],
                                 city_lts=int(row["city_lts"]), city_facility=row["facility"])
    return f"{len(matched)} street segments matched to {len(lines)} city lines ({hit.describe()})"


def apply_crashes(c: Ctx, edges) -> str:
    hit = c.json("crashes", austin.fetch_bike_crashes, cache.clip_points)
    counts: dict[int, list[int]] = {}
    for idx, crash in join.nearest_edges(edges, hit.data, config.CRASH_RADIUS_M):
        tally = counts.setdefault(idx, [0, 0])
        tally[0] += 1
        tally[1] += int(crash["severe"])
    for idx, (n, severe) in counts.items():
        e = edges.loc[idx]
        join.set_both_directions(c.region.graph, e["u"], e["v"], e["key"], crashes=n, crashes_severe=severe)
    austin.cache("crashes", c.region.name, hit.data)            # for the map layer
    return f"{len(hit.data)} bike crashes on {len(counts)} segments ({hit.describe()})"


def apply_aadt(c: Ctx, edges) -> str:
    if not txdot_aadt.covers(*c.bbox):
        return "not available here (Texas only)"
    hit = c.json("aadt", txdot_aadt.fetch_stations, cache.clip_points)
    seeds: dict[int, int] = {}
    rejected = 0
    for idx, s in join.nearest_edges(edges, hit.data, 30.0, roads_only=True):
        if s["aadt"] > AADT_CAP_BY_CLASS.get(edges.at[idx, "hw"], 60000):
            rejected += 1       # e.g. an I-35/MoPac mainline station snapped to its frontage road
            continue
        seeds[idx] = max(seeds.get(idx, 0), s["aadt"])
    n = join.propagate_by_name(c.region.graph, edges, seeds, "aadt")
    return f"{len(hit.data)} count stations -> {n} segments, {rejected} implausible skipped ({hit.describe()})"


def _to_lonlat(edges):
    return Transformer.from_crs(edges.crs, "EPSG:4326", always_xy=True)


def apply_canopy(c: Ctx, edges) -> str:
    hit = c.array("canopy", lambda b: canopy.fetch_canopy(*b), _save_canopy, _load_canopy)
    tf = _to_lonlat(edges)
    for _, row in edges.iterrows():
        xs, ys = join.sample_points(row.geometry, 10.0, offsets_m=(-6.0, 0.0, 6.0))
        lons, lats = tf.transform(xs, ys)
        shade = float((hit.data.heights(lons, lats) > config.CANOPY_TREE_M).mean())
        join.set_both_directions(c.region.graph, row["u"], row["v"], row["key"], shade=round(shade, 3))
    return f"tree shade on {len(edges)} segments ({hit.describe()})"


def apply_noise(c: Ctx, edges) -> str:
    if not usgs_3dep.covers(*c.bbox):
        return "not available here (US only)"
    hit = c.array("noise", lambda b: noise.fetch_noise(*b), _save_noise, _load_noise)
    tf = _to_lonlat(edges)
    for _, row in edges.iterrows():
        xs, ys = join.sample_points(row.geometry, 40.0)
        lons, lats = tf.transform(xs, ys)
        join.set_both_directions(c.region.graph, row["u"], row["v"], row["key"],
                                 noise_db=round(float(np.mean(hit.data.sample(lons, lats))), 1))
    return f"noise on all segments ({hit.describe()})"


def apply_stops(c: Ctx) -> str:
    hit = c.json("stops", overture.fetch_places, cache.clip_geojson)
    overture.save(c.region.name, hit.data)
    return f"{len(hit.data['features'])} Overture places ({hit.describe()})"


def apply_counters(c: Ctx) -> str:
    hit = c.json("counters", austin.fetch_counters, cache.clip_points)
    austin.cache("counters", c.region.name, hit.data)
    return f"{len(hit.data)} bike counters ({hit.describe()})"


def apply_amenities(c: Ctx) -> str:
    from cycleroutes.data.amenities import amenities_path, fetch_amenities
    path = amenities_path(c.region.name)
    if path.exists() and not c.refresh:
        return f"{len(json.loads(path.read_text())['features'])} amenities (kept; built with the network)"
    hit = c.json("amenities", lambda b: fetch_amenities(c.region.name, b), cache.clip_geojson)
    path.write_text(json.dumps(hit.data))
    return f"{len(hit.data['features'])} amenities ({hit.describe()})"


def _clear(region: Region, layer: str) -> None:
    for _, _, d in region.graph.edges(data=True):
        for attr in LAYER_ATTRS.get(layer, ()):
            d.pop(attr, None)


def apply_all(region: Region, refresh: bool = False, only: set[str] | None = None) -> dict:
    """Apply every covering, switched-on source to region.graph (in place) and re-score."""
    opts = settings.load(region.name)
    c = Ctx(region, refresh, opts)
    in_austin = austin.covers(*region.bbox)
    edges = join.edges_frame(region.graph)
    steps = {
        "elevation": lambda: apply_elevation(c),
        "canopy": lambda: apply_canopy(c, edges),
        "noise": lambda: apply_noise(c, edges),
        "aadt": lambda: apply_aadt(c, edges),
        "comfort": lambda: apply_city_comfort(c, edges) if in_austin else "not available here (Austin only)",
        "crashes": lambda: apply_crashes(c, edges) if in_austin else "not available here (Austin only)",
        "counters": lambda: apply_counters(c) if in_austin else "not available here (Austin only)",
        "stops": lambda: apply_stops(c),
        "amenities": lambda: apply_amenities(c),
    }
    report: dict[str, str] = {}
    for name, step in steps.items():
        if only and name not in only:
            continue
        if name != "elevation" and not opts["layers"].get(name, True):
            _clear(region, name)
            report[name] = "switched off"
            continue
        if name in LAYER_ATTRS:
            _clear(region, name)        # fresh values, no leftovers from a previous run
        try:
            report[name] = step()
        except Exception as exc:        # one source failing must not lose the others
            logger.exception("Source %s failed", name)
            report[name] = f"FAILED: {type(exc).__name__}: {exc}"
        logger.info("%s: %s", name, report[name])
    enrich.add_scores(region.graph)     # also re-flags risky crossings
    region.sources = {**getattr(region, "sources", {}), **report}   # --only runs add to the record
    return report
