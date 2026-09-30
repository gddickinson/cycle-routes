"""The Route object: an ordered list of graph edges plus derived geometry."""

from dataclasses import dataclass, field

import networkx as nx


@dataclass
class Route:
    graph: nx.MultiDiGraph
    edges: list[tuple[int, int, int]]          # (u, v, key) in riding order
    profile: str
    kind: str = "a_to_b"                      # "a_to_b", "loop" or "ride"
    meta: dict = field(default_factory=dict)  # e.g. requested loop distance, notices
    ctx: object = None                        # RouteContext used to plan it (bike, wind...)

    @property
    def nodes(self) -> list[int]:
        return [self.edges[0][0]] + [v for _, v, _ in self.edges] if self.edges else []

    def edge_data(self):
        for u, v, k in self.edges:
            yield self.graph.edges[u, v, k]

    @property
    def length_m(self) -> float:
        return sum(d["length"] for d in self.edge_data())

    @property
    def time_s(self) -> float:
        if self.ctx is None:
            return sum(d["time_s"] for d in self.edge_data())
        from cycleroutes.routing.context import travel_time_s
        return sum(travel_time_s(d, self.ctx) for d in self.edge_data())

    def coords(self) -> list[tuple[float, float]]:
        """(lon, lat) polyline of the whole route without duplicate joints."""
        pts: list[tuple[float, float]] = []
        for d in self.edge_data():
            seg = list(d["geometry"].coords)
            pts.extend(seg if not pts else seg[1:])
        return pts

    def elevation_profile(self) -> list[tuple[float, float]]:
        """[(distance_m, elevation_m)] along the route."""
        out: list[tuple[float, float]] = []
        dist = 0.0
        for d in self.edge_data():
            prof = d.get("elev_profile") or []
            n = len(prof)
            for i, z in enumerate(prof):
                if out and i == 0:
                    continue
                out.append((dist + d["length"] * i / max(n - 1, 1), z))
            dist += d["length"]
        return out

    def edge_set(self) -> set[tuple[int, int]]:
        """Undirected edge identities, used to compare route overlap."""
        return {(min(u, v), max(u, v)) for u, v, _ in self.edges}


def edges_from_nodes(graph: nx.MultiDiGraph, nodes: list[int], cost) -> list[tuple[int, int, int]]:
    """Pick the cheapest parallel edge between each pair of consecutive nodes."""
    out = []
    for u, v in zip(nodes[:-1], nodes[1:]):
        key = min(graph[u][v], key=lambda k: cost(graph[u][v][k], u, v))
        out.append((u, v, key))
    return out


def overlap(a: Route, b: Route) -> float:
    """Jaccard similarity of two routes' edges (0 = disjoint, 1 = identical)."""
    ea, eb = a.edge_set(), b.edge_set()
    return len(ea & eb) / max(len(ea | eb), 1)
