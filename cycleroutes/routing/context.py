"""Riding context that changes route costs: bike type, darkness, wind, heat,
closures and community reports.

A RouteContext is built per request (from the UI settings plus live weather and
work-zone data) and handed to make_cost().
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from cycleroutes import config
from cycleroutes.scoring import edge_scores, tags


@dataclass(frozen=True)
class BikeType:
    label: str
    speed_kmh: float = config.BASE_CYCLING_SPEED_KMH
    climb_factor: float = 12.0        # how much gradient slows you (e-bikes barely)
    min_surface: float = 0.0          # surfaces below this are heavily penalised
    rough_bonus: bool = False         # mountain bikes enjoy unpaved trails
    steps_penalty: float = 5.0        # carrying the bike up steps
    footway_penalty: float = 1.0      # narrow shared paths (cargo bikes, trailers)
    extra_lts_penalty: dict = field(default_factory=dict)


BIKE_TYPES = {
    "hybrid": BikeType("Hybrid / city"),
    "road": BikeType("Road bike", speed_kmh=25, min_surface=0.75),
    "gravel": BikeType("Gravel", speed_kmh=21),
    "mtb": BikeType("Mountain bike", speed_kmh=17, rough_bonus=True),
    "ebike": BikeType("E-bike", speed_kmh=24, climb_factor=3.0),
    "cargo": BikeType("Cargo / trailer", speed_kmh=16, climb_factor=16.0, steps_penalty=60.0,
                      footway_penalty=1.6),
    "kids": BikeType("Riding with kids", speed_kmh=11, climb_factor=16.0, steps_penalty=20.0,
                     extra_lts_penalty={3: 8.0, 4: 40.0}),
}


def _busy(e: dict) -> bool:
    aadt = e.get("aadt")
    if aadt:
        return aadt > 10000
    return tags.highway(e) in ("trunk", "primary") or (tags.highway(e) == "secondary" and tags.lanes(e) >= 4)


def _protected(e: dict) -> bool:
    """Physically separated from traffic: cycle track or protected lane."""
    return (tags.cycleway_kind(e) == "track" or tags.highway(e) == "cycleway"
            or "protected" in str(e.get("city_facility") or "").lower())


def _in_traffic(pred):
    """Road-type avoidance is about riding in that traffic: a protected track alongside is fine."""
    return lambda e: pred(e) and not _protected(e)


# key -> (label, predicate on an edge)
AVOID_TYPES = {
    "major": ("Major roads (primary / trunk)", _in_traffic(lambda e: tags.highway(e) in ("trunk", "primary"))),
    "secondary": ("Secondary roads", _in_traffic(lambda e: tags.highway(e) == "secondary")),
    "busy": ("Busy roads (> 10,000 vehicles/day)", _in_traffic(_busy)),
    "stressful": ("Stressful streets (LTS 3–4)", lambda e: e.get("lts", 1) >= 3),
    "unpaved": ("Unpaved surfaces", lambda e: e.get("surface_q", 1.0) < 0.6),
    "steps": ("Steps", lambda e: tags.highway(e) == "steps"),
    "sidewalks": ("Sidewalks & footpaths", lambda e: tags.highway(e) in ("footway", "pedestrian")
                  and not e.get("trail", False)),
    "service": ("Service roads & parking lots", lambda e: tags.highway(e) == "service"),
    "trails": ("Off-road trails", lambda e: e.get("trail", False)),
}


@dataclass
class RouteContext:
    bike: str = "hybrid"
    dark: bool = False
    wind_kmh: float = 0.0
    wind_from_deg: float = 0.0
    hot: bool = False                     # apparent temperature high enough to seek shade
    closed: set = field(default_factory=set)      # undirected edge keys fully closed
    restricted: set = field(default_factory=set)  # partially closed (lanes)
    edge_multipliers: dict = field(default_factory=dict)  # community reports & feedback
    avoid: frozenset = frozenset()        # keys of AVOID_TYPES
    infra_only: bool = False              # bike lanes, cycle paths & trails only (where possible)
    prefer: str = ""                      # set from the profile: "trails" / "mtb"

    @property
    def bike_type(self) -> BikeType:
        return BIKE_TYPES.get(self.bike, BIKE_TYPES["hybrid"])

    def describe(self) -> list[str]:
        notes = []
        if self.bike != "hybrid":
            notes.append(self.bike_type.label)
        if self.dark:
            notes.append("after dark: lit streets preferred")
        if self.wind_kmh >= 12:
            notes.append(f"wind {self.wind_kmh:.0f} km/h from {compass(self.wind_from_deg)}")
        if self.hot:
            notes.append("hot: shade preferred")
        if self.closed or self.restricted:
            notes.append(f"{len(self.closed)} closures avoided")
        if self.avoid:
            notes.append("avoiding " + ", ".join(AVOID_TYPES[k][0].split(" (")[0].lower()
                                                 for k in sorted(self.avoid) if k in AVOID_TYPES))
        if self.infra_only:
            notes.append("bike lanes & trails only where possible")
        return notes

    def avoided(self, edge: dict) -> bool:
        return any(AVOID_TYPES[k][1](edge) for k in self.avoid if k in AVOID_TYPES)


def compass(deg: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def headwind_kmh(edge: dict, ctx: RouteContext) -> float:
    """Wind component against the direction of travel (negative = tailwind)."""
    if ctx.wind_kmh <= 0 or "bearing" not in edge:
        return 0.0
    return ctx.wind_kmh * math.cos(math.radians(edge["bearing"] - ctx.wind_from_deg))


def travel_time_s(edge: dict, ctx: RouteContext) -> float:
    """Time for this bike type, wind included (hybrid in calm air = precomputed time_s)."""
    bt = ctx.bike_type
    if bt.label == BIKE_TYPES["hybrid"].label and ctx.wind_kmh == 0:
        return edge["time_s"]
    length = max(edge["length"], 1.0)
    grade = (edge.get("ascent", 0.0) - edge.get("descent", 0.0)) / length
    base = bt.speed_kmh * (0.6 + 0.4 * edge_scores.surface(edge)) - 0.3 * headwind_kmh(edge, ctx)
    base = max(base, 6.0)
    if tags.highway(edge) == "steps":
        return length / (2 / 3.6) + 30
    speed = max(base / (1 + bt.climb_factor * grade), 5.0) if grade > 0 else \
        min(base * (1 + 4 * -grade), config.MAX_DOWNHILL_SPEED_KMH)
    extra = edge["time_s"] - edge["length"] / (edge_scores.speed_kmh(edge) / 3.6)  # signal delays
    return length / (speed / 3.6) + max(extra, 0.0)


def edge_multiplier(edge: dict, key: tuple, ctx: RouteContext, safety_weight: float) -> float:
    """Context-dependent cost multiplier for one edge (1.0 = no change)."""
    bt = ctx.bike_type
    m = 1.0
    surf = edge.get("surface_q", 1.0)
    if bt.min_surface and surf < bt.min_surface:
        m *= 4.0
    if bt.rough_bonus and surf < 0.6:
        m *= 0.8
    hw = tags.highway(edge)
    if hw == "steps":
        m *= bt.steps_penalty
    if hw in ("footway", "pedestrian"):
        m *= bt.footway_penalty
    m *= bt.extra_lts_penalty.get(edge["lts"], 1.0)
    if ctx.dark and tags.first(edge, "lit") != "yes":
        off_road = hw in ("path", "footway", "track", "cycleway", "bridleway")
        m *= 1 + (0.5 if off_road else 0.2) * min(safety_weight, 4) / 2
    if ctx.hot:
        m *= 1 + 0.6 * (1 - edge.get("shade", 0.3))
    hw_kmh = headwind_kmh(edge, ctx)
    if hw_kmh > 0:
        m *= 1 + 0.015 * hw_kmh
    if ctx.avoid and ctx.avoided(edge):
        m *= config.AVOID_PENALTY
    if ctx.infra_only and not edge.get("bike_infra", False):
        m *= config.INFRA_ONLY_PENALTY
    if ctx.prefer == "trails" and not edge.get("trail", False):
        m *= config.PREFER_PENALTY["trails"]
    elif ctx.prefer == "mtb":
        rough_trail = edge.get("trail", False) and (edge.get("mtb_scale") is not None or surf < 0.6)
        m *= 0.8 if rough_trail else (1.0 if edge.get("trail", False) else config.PREFER_PENALTY["mtb"])
    if key in ctx.closed:
        m *= 25.0
    elif key in ctx.restricted:
        m *= 1.3
    return m * ctx.edge_multipliers.get(key, 1.0)


def is_dark(when: datetime, lat: float, lon: float) -> bool:
    from cycleroutes.services.sun import sun_times
    rise, set_ = sun_times(when.date(), lat, lon, when.tzinfo)
    return not (rise <= when <= set_)
