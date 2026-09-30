"""Hourly weather from Open-Meteo (free for non-commercial use, CC BY 4.0, no key)."""

import logging
import time
from datetime import datetime, timedelta

import requests

from cycleroutes import config

logger = logging.getLogger(__name__)
CACHE_S = 1800
_cache: dict = {}


def forecast(lat: float, lon: float) -> dict | None:
    """Hourly forecast (next 3 days) for a point, cached for 30 minutes."""
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        resp = requests.get(config.OPEN_METEO_URL, timeout=15, headers={"User-Agent": config.USER_AGENT}, params={
            "latitude": lat, "longitude": lon, "forecast_days": 3, "timezone": "auto",
            "hourly": "temperature_2m,apparent_temperature,precipitation_probability,precipitation,"
                      "wind_speed_10m,wind_direction_10m,wind_gusts_10m,is_day,uv_index"})
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Weather unavailable: %s", exc)
        return None
    data = resp.json()
    _cache[key] = (time.time(), data)
    return data


def at(lat: float, lon: float, when: datetime) -> dict | None:
    """Conditions for the hour containing `when` (local time of the forecast)."""
    data = forecast(lat, lon)
    if not data:
        return None
    hourly = data["hourly"]
    stamp = when.strftime("%Y-%m-%dT%H:00")
    if stamp not in hourly["time"]:
        return None
    i = hourly["time"].index(stamp)
    return {k: hourly[k][i] for k in hourly if k != "time"} | {"time": stamp,
                                                               "timezone": data.get("timezone")}


def along_ride(lat: float, lon: float, depart: datetime, minutes: float) -> list[dict]:
    """Hourly conditions from departure to arrival (at least one entry)."""
    out, t = [], depart.replace(minute=0, second=0, microsecond=0)
    while t <= depart + timedelta(minutes=minutes):
        w = at(lat, lon, t)
        if w:
            out.append(w)
        t += timedelta(hours=1)
    return out


def advice(conditions: list[dict]) -> list[str]:
    """Plain-language warnings for the ride window."""
    if not conditions:
        return []
    tips = []
    hot = max(c["apparent_temperature"] for c in conditions)
    wet = max(c.get("precipitation_probability") or 0 for c in conditions)
    gust = max(c.get("wind_gusts_10m") or 0 for c in conditions)
    uv = max(c.get("uv_index") or 0 for c in conditions)
    if hot >= config.HOT_APPARENT_C:
        tips.append(f"Feels like {hot:.0f}°C - carry extra water; shade is weighted in.")
    if wet >= 50:
        tips.append(f"{wet:.0f}% chance of rain - brakes and paint get slippery.")
    if gust >= 40:
        tips.append(f"Gusts to {gust:.0f} km/h - watch exposed bridges.")
    if uv >= 8:
        tips.append(f"UV index {uv:.0f} - sunscreen.")
    return tips
