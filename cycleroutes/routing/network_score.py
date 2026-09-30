"""How connected is the low-stress network? (in the spirit of PeopleForBikes' BNA)

Samples trips between random street nodes 1-5 km apart and checks whether each can
be made on LTS 1-2 streets only, with at most a 25% detour over the direct route.
"""

import random

import networkx as nx

from cycleroutes.routing.geo import haversine_m

DETOUR = 1.25


def low_stress_score(graph: nx.MultiDiGraph, samples: int = 150, seed: int = 1) -> dict:
    rng = random.Random(seed)
    nodes = list(graph.nodes)
    low = graph.edge_subgraph([(u, v, k) for u, v, k, d in graph.edges(keys=True, data=True) if d["lts"] <= 2])
    tried = ok = 0
    detours = []
    while tried < samples:
        a, b = rng.sample(nodes, 2)
        na, nb = graph.nodes[a], graph.nodes[b]
        if not 1000 <= haversine_m(na["y"], na["x"], nb["y"], nb["x"]) <= 5000:
            continue
        try:
            direct = nx.shortest_path_length(graph, a, b, weight="length")
        except nx.NetworkXNoPath:
            continue
        tried += 1
        if a in low and b in low:
            try:
                calm = nx.shortest_path_length(low, a, b, weight="length")
                detours.append(calm / direct)
                ok += calm <= DETOUR * direct
            except nx.NetworkXNoPath:
                pass
    total_km = sum(d["length"] for _, _, d in graph.edges(data=True)) / 2000
    low_km = sum(d["length"] for _, _, d in graph.edges(data=True) if d["lts"] <= 2) / 2000
    return {"score": round(100 * ok / max(tried, 1)), "trips_sampled": tried,
            "low_stress_km": round(low_km), "network_km": round(total_km),
            "median_detour": round(float(sorted(detours)[len(detours) // 2]), 2) if detours else None,
            "explanation": f"{ok} of {tried} random 1-5 km trips can be ridden on low-stress (LTS 1-2) "
                           f"streets with at most a {int((DETOUR - 1) * 100)}% detour."}
