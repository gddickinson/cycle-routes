"""Sunrise/sunset (NOAA solar-position approximation, ±1-2 minutes)."""

import math
from datetime import date, datetime, timedelta, timezone, tzinfo


def sun_times(day: date, lat: float, lon: float, tz: tzinfo | None = None) -> tuple[datetime, datetime]:
    """(sunrise, sunset) for a day at a place, as aware datetimes in `tz` (default UTC)."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    zenith = math.radians(90.833)
    cos_ha = (math.cos(zenith) / (math.cos(math.radians(lat)) * math.cos(decl))
              - math.tan(math.radians(lat)) * math.tan(decl))
    cos_ha = min(max(cos_ha, -1.0), 1.0)
    ha = math.degrees(math.acos(cos_ha))
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rise = midnight + timedelta(minutes=720 - 4 * (lon + ha) - eqtime)
    set_ = midnight + timedelta(minutes=720 - 4 * (lon - ha) - eqtime)
    tz = tz or timezone.utc
    return rise.astimezone(tz), set_.astimezone(tz)


def daylight_left(when: datetime, lat: float, lon: float) -> timedelta:
    """Time until sunset (negative once it has set)."""
    return sun_times(when.date(), lat, lon, when.tzinfo)[1] - when
