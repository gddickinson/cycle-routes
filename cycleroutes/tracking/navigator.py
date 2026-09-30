"""Live turn-by-turn progress along a planned route.

Successor to pyNav's RoutingEngine.update_location: instead of measuring the
distance to the nearest turn point, each fix is projected onto the route line,
which gives distance travelled, the next cue, remaining distance/time and a
debounced off-route signal.
"""

import math
from dataclasses import dataclass

import numpy as np

from cycleroutes import config
from cycleroutes.routing.directions import cue_sheet
from cycleroutes.routing.route import Route
from cycleroutes.tracking.nmea import Fix

EARTH_M_PER_DEG = 111_320.0
SEARCH_BACK_M = 150.0   # allow small backwards movement (GPS jitter, U-turns)


@dataclass
class Progress:
    along_m: float
    remaining_m: float
    remaining_s: float
    off_route_m: float
    off_route: bool
    arrived: bool
    next_cue: dict | None
    distance_to_cue_m: float | None
    then_cue: dict | None
    snapped: tuple[float, float]      # (lat, lon) on the route
    fraction: float

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["snapped"] = list(self.snapped)
        for k in ("along_m", "remaining_m", "remaining_s", "off_route_m", "distance_to_cue_m"):
            if d[k] is not None:
                d[k] = round(d[k], 1)
        d["fraction"] = round(self.fraction, 4)
        return d


class Navigator:
    def __init__(self, route: Route):
        coords = np.array(route.coords())               # (lon, lat)
        self.lat0 = float(coords[:, 1].mean())
        self.kx = EARTH_M_PER_DEG * math.cos(math.radians(self.lat0))
        self.xy = np.column_stack([coords[:, 0] * self.kx, coords[:, 1] * EARTH_M_PER_DEG])
        seg = np.diff(self.xy, axis=0)
        self.seg_len = np.hypot(seg[:, 0], seg[:, 1])
        self.cum = np.concatenate([[0.0], np.cumsum(self.seg_len)])
        self.total_m = float(self.cum[-1])
        self.total_s = route.time_s
        self.cues = [c.to_dict() for c in cue_sheet(route)]
        self.kind = route.kind
        self.along_m = 0.0
        self._off_count = 0

    def _project(self, x: float, y: float, lo_m: float) -> tuple[float, float, int, float]:
        """Closest point on segments starting at/after lo_m -> (along, dist, seg, t)."""
        a = self.xy[:-1]
        d = self.xy[1:] - a
        L2 = np.maximum(self.seg_len ** 2, 1e-9)
        t = np.clip(((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / L2, 0, 1)
        px, py = a[:, 0] + t * d[:, 0], a[:, 1] + t * d[:, 1]
        dist = np.hypot(px - x, py - y)
        eligible = self.cum[1:] >= lo_m
        if self.kind == "loop" and self.along_m < self.total_m * 0.5:
            # a loop starts and ends at the same place: don't jump to the finish early
            eligible &= self.cum[:-1] <= self.along_m + self.total_m * 0.5
        dist = np.where(eligible, dist, np.inf)
        i = int(np.argmin(dist))
        return float(self.cum[i] + t[i] * self.seg_len[i]), float(dist[i]), i, float(t[i])

    def update(self, fix: Fix) -> Progress:
        x, y = fix.longitude * self.kx, fix.latitude * EARTH_M_PER_DEG
        along, dist, i, t = self._project(x, y, max(0.0, self.along_m - SEARCH_BACK_M))
        usable = fix.accuracy_m is None or fix.accuracy_m <= config.MAX_ACCURACY_M
        if usable:
            self._off_count = self._off_count + 1 if dist > config.OFF_ROUTE_M else 0
            if dist <= config.OFF_ROUTE_M:
                self.along_m = along
        off_route = self._off_count >= config.OFF_ROUTE_FIXES

        remaining = max(self.total_m - self.along_m, 0.0)
        arrived = remaining <= config.ARRIVE_M and not off_route
        next_cue = then_cue = None
        to_cue = None
        upcoming = [c for c in self.cues[1:] if c["at_km"] * 1000 > self.along_m + 5]
        if upcoming:
            next_cue = upcoming[0]
            then_cue = upcoming[1] if len(upcoming) > 1 else None
            to_cue = next_cue["at_km"] * 1000 - self.along_m
        sx, sy = self.xy[i] + t * (self.xy[i + 1] - self.xy[i])
        return Progress(
            along_m=self.along_m, remaining_m=remaining,
            remaining_s=self.total_s * remaining / max(self.total_m, 1),
            off_route_m=dist, off_route=off_route, arrived=arrived,
            next_cue=next_cue, distance_to_cue_m=to_cue, then_cue=then_cue,
            snapped=(sy / EARTH_M_PER_DEG, sx / self.kx),
            fraction=self.along_m / max(self.total_m, 1))
