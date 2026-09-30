"""Run Overpass-backed downloads with fallback across public endpoints.

Public Overpass servers are frequently busy or refuse connections, so every
download is attempted on each endpoint in config.OVERPASS_ENDPOINTS in turn.
"""

import logging
import time

import osmnx as ox
import requests

from cycleroutes import config

logger = logging.getLogger(__name__)

RETRYABLE = (requests.RequestException, ox._errors.ResponseStatusCodeError)


def with_fallback(download, attempts_per_endpoint: int = 2):
    """Call download(base_url) on each endpoint until one succeeds.

    The osmnx overpass_url setting is pointed at the endpoint being tried, so
    `download` may use osmnx functions or call base_url directly.
    """
    last_exc: Exception | None = None
    for url in config.OVERPASS_ENDPOINTS:
        for attempt in range(attempts_per_endpoint):
            ox.settings.overpass_url = url
            try:
                return download(url)
            except RETRYABLE as exc:
                last_exc = exc
                logger.warning("Overpass %s failed (attempt %d): %s",
                               url, attempt + 1, str(exc)[:160])
                time.sleep(3)
    raise RuntimeError("All Overpass endpoints failed - try again later") from last_exc


def post_query(base_url: str, query: str, timeout: int = 180) -> dict:
    """POST a raw Overpass QL query and return the JSON response."""
    resp = requests.post(f"{base_url}/interpreter", data={"data": query},
                         headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
