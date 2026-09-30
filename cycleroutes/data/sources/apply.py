"""Apply every open data source that covers a region, then re-score its edges.

Raw downloads are cached in data_cache/ so re-applying is fast; `refresh=True`
downloads again. Each source is optional: failures are logged and skipped.
"""

import json
import logging

import numpy as np
from pyproj import Transformer

from cycleroutes import config
from cycleroutes.data import enrich
from cycleroutes.data.elevation import ElevationGrid
from cycleroutes.data.region import Region
from cycleroutes.data.sources import austin, canopy, join, noise, overture, txdot_aadt, usgs_3dep

logger = logging.getLogger(__name__)

# Highest plausible daily traffic per street class; a count above this means the
# station belongs to a nearby bigger road (usually a freeway beside its frontage road).
AADT_CAP_BY_CLASS = {"living_street": 3000, "residential": 8000, "service": 8000, "unclassified": 15000,
                     "tertiary": 30000, "secondary": 50000, "primary": 90000, "road": 30000}


def _cached_json(path, fetch, refresh: bool):
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = fetch()
    path.write_text(json.dumps(data))
    return data


def apply_elevation(region: Region, refresh: bool = False) -> str:
    if not usgs_3dep.covers(*region.bbox):
        return "skipped (outside US)"
    path = config.DATA_DIR / f"dem3dep_{region.name}.npz"
    if path.exists() and not refresh:
        grid = ElevationGrid.load(path)
    else:
        grid = usgs_3dep.fetch_3dep_grid(*region.bbox)
        grid.save(path)
    enrich.add_elevation(region.graph, grid)
    return f"USGS 3DEP bare earth {grid.data.shape[1]}x{grid.data.shape[0]} px"


def apply_city_comfort(region, edges, refresh=False) -> str:
    geo = _cached_json(config.DATA_DIR / f"bikefacilities_{region.name}.json",
                       lambda: austin.fetch_bike_facilities(region.bbox), refresh)
    lines = join.geojson_frame(geo)
    if lines.empty:
        return "no data"
    matched = join.overlap_join(edges, lines)
    for idx, row in matched.items():
        e = edges.loc[idx]
        join.set_both_directions(region.graph, e["u"], e["v"], e["key"],
                                 city_lts=int(row["city_lts"]), city_facility=row["facility"])
    return f"{len(matched)} street segments matched to {len(lines)} city facility lines"


def apply_crashes(region, edges, refresh=False) -> str:
    crashes = _cached_json(config.DATA_DIR / f"crashes_{region.name}.json",
                           lambda: austin.fetch_bike_crashes(region.bbox), refresh)
    counts: dict[int, list[int]] = {}
    for idx, c in join.nearest_edges(edges, crashes, config.CRASH_RADIUS_M):
        tally = counts.setdefault(idx, [0, 0])
        tally[0] += 1
        tally[1] += int(c["severe"])
    for idx, (n, severe) in counts.items():
        e = edges.loc[idx]
        join.set_both_directions(region.graph, e["u"], e["v"], e["key"], crashes=n, crashes_severe=severe)
    return f"{len(crashes)} bike crashes on {len(counts)} segments"


def apply_aadt(region, edges, refresh=False) -> str:
    if not txdot_aadt.covers(*region.bbox):
        return "skipped (outside Texas)"
    for _, _, d in region.graph.edges(data=True):
        d.pop("aadt", None)
    stations = _cached_json(config.DATA_DIR / f"aadt_{region.name}.json",
                            lambda: txdot_aadt.fetch_stations(region.bbox), refresh)
    seeds: dict[int, int] = {}
    rejected = 0
    for idx, s in join.nearest_edges(edges, stations, 30.0, roads_only=True):
        cap = AADT_CAP_BY_CLASS.get(edges.at[idx, "hw"], 60000)
        if s["aadt"] > cap:      # e.g. an I-35/MoPac mainline station snapped to its frontage road
            rejected += 1
            continue
        seeds[idx] = max(seeds.get(idx, 0), s["aadt"])
    n = join.propagate_by_name(region.graph, edges, seeds, "aadt")
    return f"{len(stations)} count stations -> measured volume on {n} segments ({rejected} implausible snaps skipped)"


def _to_lonlat(edges):
    return Transformer.from_crs(edges.crs, "EPSG:4326", always_xy=True)


def apply_canopy(region, edges, refresh=False) -> str:
    grid = canopy.fetch_canopy(*region.bbox)
    tf = _to_lonlat(edges)
    for idx, row in edges.iterrows():
        xs, ys = join.sample_points(row.geometry, 10.0, offsets_m=(-6.0, 0.0, 6.0))
        lons, lats = tf.transform(xs, ys)
        shade = float((grid.heights(lons, lats) > config.CANOPY_TREE_M).mean())
        join.set_both_directions(region.graph, row["u"], row["v"], row["key"], shade=round(shade, 3))
    return f"tree shade on {len(edges)} segments"


def apply_noise(region, edges, refresh=False) -> str:
    grid = noise.fetch_noise(*region.bbox)
    tf = _to_lonlat(edges)
    for idx, row in edges.iterrows():
        xs, ys = join.sample_points(row.geometry, 40.0)
        lons, lats = tf.transform(xs, ys)
        join.set_both_directions(region.graph, row["u"], row["v"], row["key"],
                                 noise_db=round(float(np.mean(grid.sample(lons, lats))), 1))
    return "road/aviation noise on all segments"


def apply_stops(region, refresh=False) -> str:
    path = config.DATA_DIR / f"stops_{region.name}.geojson"
    if not path.exists() or refresh:
        overture.save(region.name, overture.fetch_places(region.bbox))
    return f"{len(overture.load(region.name)['features'])} Overture stops cached"


def apply_counters(region, refresh=False) -> str:
    if not austin.covers(*region.bbox):
        return "skipped"
    data = _cached_json(config.DATA_DIR / f"counters_{region.name}.json",
                        lambda: austin.fetch_counters(region.bbox), refresh)
    return f"{len(data)} bike counters cached"


def apply_all(region: Region, refresh: bool = False, only: set[str] | None = None) -> dict:
    """Apply every covering source to region.graph (in place) and re-score. Returns a report."""
    report: dict[str, str] = {}
    edges = join.edges_frame(region.graph)
    steps = {
        "elevation": lambda: apply_elevation(region, refresh),
        "canopy": lambda: apply_canopy(region, edges, refresh),
        "noise": lambda: apply_noise(region, edges, refresh) if usgs_3dep.covers(*region.bbox) else "skipped (outside US)",
        "aadt": lambda: apply_aadt(region, edges, refresh),
        "comfort": lambda: apply_city_comfort(region, edges, refresh) if austin.covers(*region.bbox) else "skipped",
        "crashes": lambda: apply_crashes(region, edges, refresh) if austin.covers(*region.bbox) else "skipped",
        "counters": lambda: apply_counters(region, refresh),
        "stops": lambda: apply_stops(region, refresh),
    }
    for name, step in steps.items():
        if only and name not in only:
            continue
        try:
            report[name] = step()
        except Exception as exc:   # one source failing must not lose the others
            logger.exception("Source %s failed", name)
            report[name] = f"FAILED: {type(exc).__name__}: {exc}"
        logger.info("%s: %s", name, report[name])
    enrich.add_scores(region.graph)   # also re-flags risky crossings
    region.sources = {**getattr(region, "sources", {}), **report}   # --only runs add to the record
    return report
