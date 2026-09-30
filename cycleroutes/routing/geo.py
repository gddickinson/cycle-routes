"""Spherical geometry helpers (ported from pyNav's routing/geocoding utilities)."""

import math

import numpy as np

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres; works on scalars or numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing from point 1 to point 2 (0-360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination(lat: float, lon: float, bearing: float, dist_m: float) -> tuple[float, float]:
    """Point reached travelling dist_m from (lat, lon) on a bearing."""
    d = dist_m / EARTH_RADIUS_M
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def compass_word(bearing: float) -> str:
    return ["north", "northeast", "east", "southeast",
            "south", "southwest", "west", "northwest"][round(bearing / 45) % 8]


class NodeIndex:
    """Nearest-node lookup over a graph's nodes (brute force; fine for city graphs)."""

    def __init__(self, graph):
        self.ids = np.array(list(graph.nodes))
        self.lat = np.array([graph.nodes[n]["y"] for n in self.ids])
        self.lon = np.array([graph.nodes[n]["x"] for n in self.ids])

    def nearest(self, lat: float, lon: float) -> tuple[int, float]:
        """(node id, distance in metres) of the closest node."""
        d = haversine_m(lat, lon, self.lat, self.lon)
        i = int(np.argmin(d))
        return int(self.ids[i]), float(d[i])
