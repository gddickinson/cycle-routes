// The browser routing engine for the demo area: model + demo graph from the API, built and scored once per visit.
import { api } from './core.js';
import { buildGraph, edgeAt } from './demo_graph.js';
import { Router, Route, ukey } from './router_engine.js';

let pending = null;
export function engine() {
  if (!pending) {
    pending = Promise.all([api('/model'), api('/demo')]).then(([model, demo]) => {
      const t0 = performance.now();
      const graph = buildGraph(demo, model);
      const buildMs = performance.now() - t0;
      // each street drawn once (a two-way street is two directed edges with the same geometry)
      const seen = new Set(), draw = [];
      for (const e of graph.edges) {
        const k = ukey(e.u, e.v) + '/' + e.key;
        if (!seen.has(k)) { seen.add(k); draw.push(e); }
      }
      draw.sort((a, b) => b.lts - a.lts);   // calm streets drawn last, on top
      return { model, demo, graph, router: new Router(graph), draw, buildMs };
    });
  }
  return pending;
}

// Route from an edge-triple list (as the Python API returns it).
export function routeFromTriples(eng, triples, profile, kind = 'a_to_b', ctx = null) {
  const edges = triples.map(([u, v, k]) => edgeAt(eng.graph, u, v, k));
  if (edges.some(e => !e)) throw new Error('Route does not match the demo graph');
  return new Route(eng.graph, edges, profile, { kind, ctx });
}
