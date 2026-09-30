"""Split a long route into daily stages, suggesting somewhere to stay at each break."""

from cycleroutes.routing.route import Route
from cycleroutes.routing.stops import along


def split_stages(route: Route, km_per_day: float, stays: list[dict]) -> list[dict]:
    """[{day, from_km, to_km, km, climb_m, stay}] with overnight options near each break."""
    total_km = route.length_m / 1000
    if km_per_day <= 0 or total_km <= km_per_day:
        return [{"day": 1, "from_km": 0.0, "to_km": round(total_km, 2), "km": round(total_km, 2),
                 "climb_m": round(sum(d.get("ascent", 0) for d in route.edge_data())), "stay": None}]
    candidates = along(route, stays, within_m=1500)
    prof = route.elevation_profile()
    days, start, day = [], 0.0, 1
    while start < total_km - 1e-6:
        target = start + km_per_day
        stay = None
        if target < total_km:
            near = [s for s in candidates if abs(s["at_km"] - target) <= km_per_day * 0.2]
            stay = min(near, key=lambda s: abs(s["at_km"] - target) + s["off_route_m"] / 1000, default=None)
            end = stay["at_km"] if stay else target
        else:
            end = total_km
        climb = sum(max(b[1] - a[1], 0) for a, b in zip(prof[:-1], prof[1:])
                    if start * 1000 <= a[0] < end * 1000)
        days.append({"day": day, "from_km": round(start, 2), "to_km": round(end, 2),
                     "km": round(end - start, 2), "climb_m": round(climb), "stay": stay})
        start, day = end, day + 1
    return days
