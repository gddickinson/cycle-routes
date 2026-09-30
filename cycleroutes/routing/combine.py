"""Build on an existing route: get there from somewhere, turn it into a loop, add stops
and a final destination.

    extend_route(router, base, start=..., join="start" | "nearest",
                 after="end" | "return" | "destination", stops=[...], destination=...)

The result is one Route whose meta["legs"] records which edges are the approach, the
original route and the onward part, so the map can draw them differently.
"""

from cycleroutes.routing import geo
from cycleroutes.routing.route import Route, edges_from_nodes
from cycleroutes.routing.router import Router, RoutingError, shortest_nodes

LEG_LABELS = {"approach": "Getting there", "route": "The route", "onward": "Onward"}


def _leg(router: Router, cost, a: int, b: int) -> list[tuple[int, int, int]]:
    if a == b:
        return []
    return edges_from_nodes(router.graph, shortest_nodes(router.graph, a, b, cost), cost)


def _join_index(base: Route, point) -> int:
    """Index of the route node nearest to point (so the route can be joined there)."""
    nodes = base.nodes
    g = base.graph
    dists = [float(geo.haversine_m(point[0], point[1], g.nodes[n]["y"], g.nodes[n]["x"])) for n in nodes]
    return min(range(len(nodes) - 1 if len(nodes) > 1 else 1), key=lambda i: dists[i])


def extend_route(router: Router, base: Route, start=None, join: str = "start", after: str = "end",
                 stops=None, destination=None, profile="balanced", ctx=None) -> Route:
    if base.graph is not router.graph:
        raise RoutingError("That route was planned for a different travel mode")
    if after == "destination" and destination is None:
        raise RoutingError("Choose a final destination")
    if after == "return" and start is None and base.nodes[0] == base.nodes[-1]:
        raise RoutingError("Choose a start point to return to")
    cost = router.cost_for(profile, ctx)
    core = list(base.edges)
    is_loop = bool(core) and core[0][0] == core[-1][1]

    # 1. where to join the route
    if start is not None and join == "nearest" and core:
        i = _join_index(base, start)
        core = core[i:] + core[:i] if is_loop else core[i:]      # a loop can start anywhere
    if not core:
        raise RoutingError("Nothing left of the route after joining it there")
    join_node, route_end = core[0][0], core[-1][1]

    # 2. getting there
    start_node = router.snap(*start) if start is not None else join_node
    approach = _leg(router, cost, start_node, join_node)

    # 3. afterwards: extra stops, then the end / back to start / a destination
    waypoints = [router.snap(*p) for p in (stops or [])]
    if after == "return":
        waypoints.append(start_node if start is not None else core[0][0])
    elif after == "destination":
        waypoints.append(router.snap(*destination))
    onward, here = [], route_end
    for w in waypoints:
        onward += _leg(router, cost, here, w)
        here = w

    edges = approach + core + onward
    route = Route(router.graph, edges, base.profile, ctx=ctx,
                  kind="loop" if edges and edges[0][0] == edges[-1][1] else "a_to_b")
    bounds = {"approach": (0, len(approach)), "route": (len(approach), len(approach) + len(core)),
              "onward": (len(approach) + len(core), len(edges))}
    lengths = {k: round(sum(route.graph.edges[e]["length"] for e in edges[a:b]) / 1000, 2)
               for k, (a, b) in bounds.items()}
    route.meta.update(leg_bounds=bounds, legs=[{"kind": k, "label": LEG_LABELS[k], "km": lengths[k]}
                                               for k in bounds if lengths[k] > 0])
    return route


def route_from_edges(graph, edges: list, profile: str, kind: str, title: str | None = None) -> Route:
    """Rebuild a saved route; fails if the network changed since it was saved."""
    edges = [tuple(e) for e in edges]
    if not all(graph.has_edge(*e) for e in edges):
        raise RoutingError("This saved route no longer matches the map (the area was rebuilt) - plan it again")
    return Route(graph, edges, profile, kind=kind, meta={"title": title} if title else {})
