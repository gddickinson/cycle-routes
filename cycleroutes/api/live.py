"""Time-varying data for routing: work-zone closures, community reports, weather, daylight.

Turns a request's settings (bike type, departure time, 'use weather') into a
RouteContext, plus a human-readable summary for the UI.
"""

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from cycleroutes import config
from cycleroutes.community.store import HAZARD_TYPES, CommunityStore
from cycleroutes.data.region import Region
from cycleroutes.data.sources import austin, join
from cycleroutes.routing.context import BIKE_TYPES, RouteContext, compass
from cycleroutes.services import weather
from cycleroutes.services.sun import sun_times

logger = logging.getLogger(__name__)
WORKZONE_REFRESH_S = 3600
HAZARD_RADIUS_M = 25.0


class LiveData:
    def __init__(self, region: Region, community: CommunityStore):
        self.region, self.community = region, community
        self._edges = None
        self._zones: dict | None = None
        self._zones_at = 0.0
        self._closed: set = set()
        self._restricted: set = set()
        self._lock = threading.Lock()
        self.tz = ZoneInfo("America/Chicago") if austin.covers(*region.bbox) else None

    @property
    def edges(self):
        if self._edges is None:
            self._edges = join.edges_frame(self.region.graph)
        return self._edges

    def _key(self, idx) -> tuple[int, int]:
        r = self.edges.loc[idx]
        return (min(r["u"], r["v"]), max(r["u"], r["v"]))

    # --- work zones -----------------------------------------------------------------
    def work_zones(self) -> dict:
        """Active work zones (refreshed hourly), with the streets they close mapped."""
        with self._lock:
            if self._zones is not None and time.time() - self._zones_at < WORKZONE_REFRESH_S:
                return self._zones
            if not austin.covers(*self.region.bbox):
                self._zones = {"type": "FeatureCollection", "features": []}
                return self._zones
            try:
                zones = austin.fetch_work_zones(self.region.bbox)
            except Exception as exc:   # live feed down: keep the last good copy
                logger.warning("Work zones unavailable: %s", exc)
                return self._zones or {"type": "FeatureCollection", "features": []}
            closed, restricted = set(), set()
            frame = join.geojson_frame(zones)
            if not frame.empty:
                for idx, row in join.overlap_join(self.edges, frame, buffer_m=12, min_overlap=0.5).items():
                    (closed if row["closed"] else restricted).add(self._key(idx))
            self._zones, self._zones_at = zones, time.time()
            self._closed, self._restricted = closed, restricted - closed
            logger.info("Work zones: %d closed / %d restricted street segments", len(closed), len(restricted))
            return zones

    # --- community -------------------------------------------------------------------
    def report_multipliers(self) -> dict:
        mult: dict[tuple[int, int], float] = {}
        hazards = self.community.hazards()
        pts = [{"lat": h["lat"], "lon": h["lon"], "kind": h["kind"]} for h in hazards]
        for idx, h in join.nearest_edges(self.edges, pts, HAZARD_RADIUS_M):
            key = self._key(idx)
            mult[key] = max(mult.get(key, 1.0), HAZARD_TYPES[h["kind"]][1])
        for key, score in self.community.street_scores().items():
            mult[key] = mult.get(key, 1.0) * min(max(1 - 0.12 * score, 0.6), 2.0)
        return mult

    # --- context -----------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(self.tz) if self.tz else datetime.now().astimezone()

    def parse_depart(self, depart: str | None) -> datetime:
        if not depart:
            return self.now()
        dt = datetime.fromisoformat(depart)
        return dt if dt.tzinfo else dt.replace(tzinfo=self.now().tzinfo)

    def context(self, bike: str = "hybrid", depart: str | None = None, use_weather: bool = True,
                use_closures: bool = True) -> tuple[RouteContext, dict]:
        when = self.parse_depart(depart)
        lat, lon = self.region.lat, self.region.lon
        rise, sunset = sun_times(when.date(), lat, lon, when.tzinfo)
        ctx = RouteContext(bike=bike if bike in BIKE_TYPES else "hybrid",
                           dark=not (rise <= when <= sunset))
        info = {"depart": when.isoformat(timespec="minutes"), "sunrise": rise.strftime("%H:%M"),
                "sunset": sunset.strftime("%H:%M"), "dark": ctx.dark,
                "bike": ctx.bike, "bike_label": ctx.bike_type.label}
        if use_weather:
            w = weather.at(lat, lon, when)
            if w:
                ctx.wind_kmh, ctx.wind_from_deg = w["wind_speed_10m"], w["wind_direction_10m"]
                ctx.hot = w["apparent_temperature"] >= config.HOT_APPARENT_C
                info["weather"] = {"temp_c": w["temperature_2m"], "feels_c": w["apparent_temperature"],
                                   "rain_pct": w.get("precipitation_probability"),
                                   "wind_kmh": w["wind_speed_10m"], "gust_kmh": w.get("wind_gusts_10m"),
                                   "wind_from": compass(w["wind_direction_10m"]), "uv": w.get("uv_index")}
                info["advice"] = weather.advice([w])
        if use_closures:
            self.work_zones()
            ctx.closed, ctx.restricted = set(self._closed), set(self._restricted)
            info["closures"] = len(self._closed)
        ctx.edge_multipliers = self.report_multipliers()
        info["reports"] = len(self.community.hazards())
        info["notes"] = ctx.describe()
        return ctx, info
