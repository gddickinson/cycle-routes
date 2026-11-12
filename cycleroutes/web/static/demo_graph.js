// Build the scored street graph from the compact demo-area JSON (written by scripts/make_demo_area.py, read in
// Python by cycleroutes/web/demo_area.py). Edges keep their raw OSM tags; every score is recomputed here.
import { setModel, scoreEdge, addCrossings } from './scoring_engine.js';

function line(flat) {
  const pts = [];
  for (let i = 0; i < flat.length; i += 2) pts.push([flat[i], flat[i + 1]]);
  return pts;
}

export function buildGraph(demo, model) {
  setModel(model);
  const n = demo.nodes.lat.length;
  const signals = new Set(demo.nodes.signals);
  const g = {
    area: demo.area, base_kmh: model.scores.base_kmh,
    lats: demo.nodes.lat, lons: demo.nodes.lon,
    nodes: Array.from({ length: n }, (_, i) => ({ signals: signals.has(i), risky_crossing: false, busy_names: [] })),
    succ: Array.from({ length: n }, () => new Map()), pred: Array.from({ length: n }, () => new Map()),
    out: Array.from({ length: n }, () => []), inn: Array.from({ length: n }, () => []), edges: [],
  };
  const geoms = demo.geoms.map(line);
  for (const row of demo.edges) {
    const [u, v, key, ts, length, scenic, ascent, descent, rank, gi, ni] = row;
    const fwd = gi >= 0, idx = fwd ? gi : -gi - 1;
    const geometry = fwd ? geoms[idx] : geoms[idx].slice().reverse();
    const prof = demo.elev[idx];
    const e = { ...demo.tagsets[ts], u, v, key, length, scenic, ascent, descent, route_rank: rank,
      route_names: ni >= 0 ? demo.route_names[ni] : [], geometry, elev_profile: fwd ? prof : prof.slice().reverse() };
    scoreEdge(e, signals.has(v));
    if (!g.succ[u].has(v)) g.succ[u].set(v, []);
    g.succ[u].get(v).push(e);
    if (!g.pred[v].has(u)) g.pred[v].set(u, []);
    g.pred[v].get(u).push(e);
    g.out[u].push(e); g.inn[v].push(e);
    g.edges.push(e);
  }
  addCrossings(g);
  return g;
}

// Find the edge (u, v, key) of a graph, for routes stored as edge triples.
export function edgeAt(g, u, v, key) {
  const list = g.succ[u].get(v);
  return list && list.find(e => e.key === key);
}
