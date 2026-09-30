"""Place search via Nominatim - a Qt-free port of pyNav's NominatimProvider.

Respects the Nominatim usage policy: identifying User-Agent, max 1 request/s,
and results are cached in memory.
"""

import logging
import threading
import time
from dataclasses import asdict, dataclass

import requests

from cycleroutes import config

logger = logging.getLogger(__name__)


@dataclass
class GeocodingResult:
    address: str
    latitude: float
    longitude: float
    place_type: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


class NominatimGeocoder:
    rate_limit_s = 1.0

    def __init__(self, server_url: str = config.NOMINATIM_URL):
        self.server_url = server_url.rstrip("/")
        self._last = 0.0
        self._lock = threading.Lock()
        self._cache: dict[tuple, list[GeocodingResult]] = {}

    def _respect_rate_limit(self) -> None:
        wait = self.rate_limit_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def search(self, query: str, viewbox: tuple[float, float, float, float] | None = None,
               limit: int = 5) -> list[GeocodingResult]:
        """Search for a place. viewbox = (south, west, north, east) biases/limits results."""
        key = (query.strip().lower(), viewbox)
        if key in self._cache:
            return self._cache[key]
        params = {"q": query, "format": "json", "limit": limit}
        if viewbox:
            s, w, n, e = viewbox
            params.update(viewbox=f"{w},{n},{e},{s}", bounded=1)
        with self._lock:
            self._respect_rate_limit()
            try:
                resp = requests.get(f"{self.server_url}/search", params=params,
                                    headers={"User-Agent": config.USER_AGENT}, timeout=10)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.error("Nominatim error: %s", exc)
                return []
        results = [GeocodingResult(item.get("display_name", ""), float(item["lat"]),
                                   float(item["lon"]), item.get("type", "unknown"))
                   for item in resp.json()]
        self._cache[key] = results
        return results
