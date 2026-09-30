"""Point-to-point routing on the scored graph with preference-weighted costs."""

import logging

import networkx as nx

from cycleroutes import config
from cycleroutes.config import Profile
from cycleroutes.routing.context import RouteContext, edge_multiplier, travel_time_s
from cycleroutes.routing.geo import NodeIndex
from cycleroutes.routing.route import Route, edges_from_nodes, overlap
from cycleroutes.scoring import tags

logger = logging.getLogger(__name__)

TIME_TO_METRES = config.BASE_CYCLING_SPEED_KMH / 3.6  # compare time and distance costs
CLIMB_COST_M = 8.0      # 1 m of climbing ~ 8 m of flat riding, per unit hills weight
MAX_SNAP_M = 500.0


class RoutingError(ValueError):
    pass


def make_cost(profile: Profile, penalties: dict | None = None, graph: nx.MultiDiGraph | None = None,
              ctx: RouteContext | None = None):
    """Edge-attribute -> cost function for a profile.

    penalties: optional {(u, v): multiplier} used by loop generation to
    discourage re-riding edges. graph + ctx enable crossing penalties and the
    riding context (bike type, darkness, wind, heat, closures, reports).
    """
    w = profile.weights()
    penalties = penalties or {}
    ctx = ctx or RouteContext()
    nodes = graph.nodes if graph is not None else None
    hills_w = w["hills"] * (0.3 if ctx.bike == "ebike" else 1.0)

    def cost(d: dict, u: int | None = None, v: int | None = None) -> float:
        base = travel_time_s(d, ctx) * TIME_TO_METRES if profile.time else d["length"]
        factor = (1 + w["safety"] * (1 - d["safety"]) + w["fun"] * (1 - d["fun"])
                  + w["traffic"] * (1 - d["quiet"]) + w["surface"] * (1 - d["surface_q"])
                  + w["shade"] * (1 - d.get("shade", 0.3)))
        c = base * factor * profile.lts_penalty.get(d["lts"], 1.0) * d.get("awkward", 1.0)
        c += hills_w * d.get("ascent", 0.0) * CLIMB_COST_M
        if u is not None:
            key = (min(u, v), max(u, v))
            c *= edge_multiplier(d, key, ctx, w["safety"]) * penalties.get(key, 1.0)
            if nodes is not None and profile.crossings:
                nd = nodes[v]
                if nd.get("risky_crossing") and d["lts"] <= 2 and \
                        (tags.first(d, "name") or "?") not in nd.get("busy_names", ()):
                    c += profile.crossings * config.CROSSING_COST_M
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

    def cost_for(self, profile, ctx: RouteContext | None = None, penalties: dict | None = None):
        _, prof = resolve_profile(profile)
        return make_cost(prof, penalties, self.graph, ctx)

    def route(self, start: tuple[float, float], end: tuple[float, float], profile="balanced",
              via: list[tuple[float, float]] | None = None, ctx: RouteContext | None = None) -> Route:
        """Route start -> (via points...) -> end."""
        name, prof = resolve_profile(profile)
        cost = make_cost(prof, None, self.graph, ctx)
        stops = [self.snap(*p) for p in [start, *(via or []), end]]
        stops = [n for i, n in enumerate(stops) if i == 0 or n != stops[i - 1]]
        if len(stops) < 2:
            raise RoutingError("Start and end are the same point")
        edges = []
        for a, b in zip(stops[:-1], stops[1:]):
            edges += edges_from_nodes(self.graph, shortest_nodes(self.graph, a, b, cost), cost)
        route = Route(self.graph, edges, name, ctx=ctx)
        if via:
            route.meta["via"] = [list(p) for p in via]
        return route

    def family_route(self, start, end, via=None, ctx=None, fastest_m: float | None = None) -> Route:
        """Family route, relaxed when the fully low-stress option is an absurd detour."""
        route = self.route(start, end, "family", via, ctx)
        fastest_m = fastest_m or self.route(start, end, "fastest", via, ctx).length_m
        if route.length_m > config.FAMILY_MAX_DETOUR * fastest_m:
            detoured = route.length_m
            relaxed = Profile("Family (relaxed)", "Short busier sections allowed", safety=5, traffic=2,
                              hills=1, crossings=4, lts_penalty={3: 2.0, 4: 8.0})
            cost = make_cost(relaxed, None, self.graph, ctx)
            stops = [self.snap(*p) for p in [start, *(via or []), end]]
            edges = []
            for a, b in zip(stops[:-1], stops[1:]):
                if a != b:
                    edges += edges_from_nodes(self.graph, shortest_nodes(self.graph, a, b, cost), cost)
            route = Route(self.graph, edges, "family", ctx=ctx)
            route.meta["notice"] = (f"A fully low-stress route would be {detoured / 1000:.1f} km "
                                    f"({detoured / fastest_m:.1f}x the direct route), so this one "
                                    "uses short busier sections - take extra care on red stretches.")
        return route

    def alternatives(self, start, end, profiles=None, max_overlap=0.9, via=None,
                     ctx: RouteContext | None = None) -> list[Route]:
        """One route per profile, dropping near-duplicates (the first one wins)."""
        routes: list[Route] = []
        fastest_m = None
        for name in profiles or config.PROFILES:
            if name == "family":
                r = self.family_route(start, end, via, ctx, fastest_m)
            else:
                r = self.route(start, end, name, via, ctx)
            if name == "fastest":
                fastest_m = r.length_m
            dup = next((o for o in routes if overlap(o, r) >= max_overlap), None)
            if dup:
                dup.meta.setdefault("also_matches", []).append(name)
            else:
                routes.append(r)
        return routes
