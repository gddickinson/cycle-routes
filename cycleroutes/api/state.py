"""Process-wide application state shared by the API routers."""

import os
import uuid
from collections import OrderedDict
from functools import cached_property
from pathlib import Path

from fastapi import HTTPException

from cycleroutes import config
from cycleroutes.api.serialize import route_payload
from cycleroutes.data.amenities import load_amenities
from cycleroutes.data.region import load_region
from cycleroutes.export.formats import network_geojson
from cycleroutes.routing.catalog import load_catalog
from cycleroutes.routing.router import Router
from cycleroutes.services.geocoding import NominatimGeocoder
from cycleroutes.tracking.navigator import Navigator
from cycleroutes.tracking.providers import ProviderManager
from cycleroutes.tracking.store import RideStore

MAX_STORED_ROUTES = 200


class AppState:
    """Region, router, recently computed routes (for export by id), rides and GPS sources."""

    def __init__(self, region_name: str, rides_db: Path = config.RIDES_DB):
        self.region = load_region(region_name)
        self.router = Router(self.region.graph)
        self.geocoder = NominatimGeocoder()
        self.routes: OrderedDict[str, tuple] = OrderedDict()
        self.navigators: dict[str, Navigator] = {}
        self.rides = RideStore(rides_db)
        self.gps = ProviderManager(include_ip=os.environ.get("CYCLEROUTES_IP_LOCATION") == "1",
                                   scan_serial=os.environ.get("CYCLEROUTES_SERIAL_GPS") == "1")
        self.suggested = []
        for route, stats, title in load_catalog(self.region):
            self.suggested.append(self.store(route, stats, title))

    def store(self, route, stats, title=None) -> dict:
        rid = uuid.uuid4().hex[:10]
        self.routes[rid] = (route, stats, title)
        while len(self.routes) > MAX_STORED_ROUTES + len(self.suggested):
            old, _ = self.routes.popitem(last=False)
            self.navigators.pop(old, None)
        return route_payload(rid, route, stats, title)

    def get(self, rid: str):
        if rid not in self.routes:
            raise HTTPException(404, "Route expired - please plan it again")
        return self.routes[rid]

    def navigator(self, rid: str, restart: bool = False) -> Navigator:
        if restart or rid not in self.navigators:
            self.navigators[rid] = Navigator(self.get(rid)[0])
        return self.navigators[rid]

    @cached_property
    def network(self) -> dict:
        return network_geojson(self.region.graph)

    @cached_property
    def amenities(self) -> dict:
        return load_amenities(self.region.name)


_state: AppState | None = None


def state() -> AppState:
    global _state
    if _state is None:
        _state = AppState(os.environ.get("CYCLEROUTES_REGION", config.DEFAULT_REGION["name"]),
                          Path(os.environ.get("CYCLEROUTES_RIDES_DB", config.RIDES_DB)))
    return _state


def set_state(value: AppState | None) -> None:
    """Install (or clear) the state explicitly - used by tests."""
    global _state
    _state = value


def latlon(text: str) -> tuple[float, float]:
    try:
        lat, lon = (float(v) for v in text.split(","))
    except ValueError as exc:
        raise HTTPException(400, f"Expected 'lat,lon', got '{text}'") from exc
    return lat, lon
