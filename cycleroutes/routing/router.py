"""Point-to-point routing on the scored graph with preference-weighted costs."""

import logging

import networkx as nx

from cycleroutes import config
from cycleroutes.config import Profile
from cycleroutes.routing.geo import NodeIndex
from cycleroutes.routing.route import Route, edges_from_nodes, overlap

logger = logging.getLogger(__name__)

TIME_TO_METRES = config.BASE_CYCLING_SPEED_KMH / 3.6  # compare time and distance costs
CLIMB_COST_M = 8.0      # 1 m of climbing ~ 8 m of flat riding, per unit hills weight
MAX_SNAP_M = 500.0


class RoutingError(ValueError):
    pass


def make_cost(profile: Profile, penalties: dict | None = None):
    """Edge-attribute -> cost function for a profile.

    penalties: optional {(u, v): multiplier} used by loop generation to
    discourage re-riding edges.
    """
    w = profile.weights()

    penalties = penalties or {}

    def cost(d: dict, u: int | None = None, v: int | None = None) -> float:
        base = d["time_s"] * TIME_TO_METRES if profile.time else d["length"]
        factor = (1 + w["safety"] * (1 - d["safety"]) + w["fun"] * (1 - d["fun"])
                  + w["traffic"] * (1 - d["quiet"]) + w["surface"] * (1 - d["surface_q"]))
        c = base * factor * profile.lts_penalty.get(d["lts"], 1.0) * d.get("awkward", 1.0)
        c += w["hills"] * d.get("ascent", 0.0) * CLIMB_COST_M
        if penalties and u is not None:
            c *= penalties.get((min(u, v), max(u, v)), 1.0)
        return c

    return cost


def custom_profile(**weights) -> Profile:
    """Profile from user sliders, e.g. custom_profile(safety=3, hills=1)."""
    fields = {k: float(v) for k, v in weights.items() if k in Profile.__dataclass_fields__
              and k not in ("label", "description", "time", "lts_penalty")}
    return Profile("Custom", "Your own mix", **fields)


def resolve_profile(name_or_profile) -> tuple[str, Profile]:
    if isinstance(name_or_profile, Profile):
        return "custom", name_or_profile
    if name_or_profile not in config.PROFILES:
        raise RoutingError(f"Unknown profile '{name_or_profile}'")
    return name_or_profile, config.PROFILES[name_or_profile]


def shortest_nodes(graph, source: int, target: int, cost) -> list[int]:
    def weight(u, v, d):
        return min(cost(e, u, v) for e in d.values())
    try:
        return nx.shortest_path(graph, source, target, weight=weight)
    except nx.NetworkXNoPath as exc:
        raise RoutingError("No rideable path between these points") from exc


class Router:
    """Routes on one region's graph."""

    def __init__(self, graph: nx.MultiDiGraph):
        self.graph = graph
        self.index = NodeIndex(graph)

    def snap(self, lat: float, lon: float) -> int:
        node, dist = self.index.nearest(lat, lon)
        if dist > MAX_SNAP_M:
            raise RoutingError(f"Point ({lat:.5f}, {lon:.5f}) is {dist:.0f} m from the "
                               "nearest rideable street - outside the mapped region?")
        return node

    def route(self, start: tuple[float, float], end: tuple[float, float],
              profile="balanced") -> Route:
        name, prof = resolve_profile(profile)
        cost = make_cost(prof)
        a, b = self.snap(*start), self.snap(*end)
        if a == b:
            raise RoutingError("Start and end are the same point")
        nodes = shortest_nodes(self.graph, a, b, cost)
        return Route(self.graph, edges_from_nodes(self.graph, nodes, cost), name)

    def alternatives(self, start, end, profiles=None, max_overlap=0.9) -> list[Route]:
        """One route per profile, dropping near-duplicates (the first one wins)."""
        routes: list[Route] = []
        for name in profiles or config.PROFILES:
            r = self.route(start, end, name)
            dup = next((o for o in routes if overlap(o, r) >= max_overlap), None)
            if dup:
                dup.meta.setdefault("also_matches", []).append(name)
            else:
                routes.append(r)
        return routes
