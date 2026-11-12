// Route search: port of cycleroutes/routing/router.py and route.py. Shortest paths use the same bidirectional
// Dijkstra as networkx (nx.shortest_path), with the same tie-breaking, so routes match the Python node for node.
import * as tags from './osm_tags.js';
import { model } from './scoring_engine.js';
import { makeContext, edgeMultiplier, travelTimeS } from './context.js';
import { nearestNode, pyFixed, pySum } from './geo.js';

export class RoutingError extends Error {}

export const ukey = (u, v) => (u < v ? u + '-' + v : v + '-' + u);

// --- cost -------------------------------------------------------------------------
export function makeCost(profile, penalties = null, graph = null, ctx = null) {
  const R = model().routing;
  const w = { safety: profile.safety, fun: profile.fun, traffic: profile.traffic, hills: profile.hills,
    surface: profile.surface, shade: profile.shade };
  penalties = penalties || new Map();
  ctx = ctx || makeContext();
  if (profile.prefer) ctx = { ...ctx, prefer: profile.prefer };
  const nodes = graph ? graph.nodes : null;
  const hillsW = w.hills * (ctx.bike === 'ebike' ? 0.3 : 1.0);
  const [kS, kQ, kF, kL] = ctx.osm_only ? ['safety_osm', 'quiet_osm', 'fun_osm', 'lts_osm'] : ['safety', 'quiet', 'fun', 'lts'];
  const ltsPen = profile.lts_penalty || {};
  return function cost(d, u = null, v = null) {
    const base = profile.time ? travelTimeS(d, ctx) * R.time_to_metres : d.length;
    const factor = 1 + w.safety * (1 - (d[kS] ?? d.safety)) + w.fun * (1 - (d[kF] ?? d.fun))
      + w.traffic * (1 - (d[kQ] ?? d.quiet)) + w.surface * (1 - d.surface_q)
      + w.shade * (ctx.osm_only ? 0.0 : 1 - (d.shade ?? 0.3));
    let c = base * factor * (ltsPen[d[kL] ?? d.lts] ?? 1.0) * (d.awkward ?? 1.0);
    c += hillsW * (d.ascent ?? 0) * R.climb_cost_m;
    if (u !== null) {
      const key = ukey(u, v);
      c *= edgeMultiplier(d, key, ctx, w.safety) * (penalties.get(key) ?? 1.0);
      if (nodes && profile.crossings) {
        const nd = nodes[v];
        if (nd.risky_crossing && d.lts <= 2 && !nd.busy_names.includes(tags.first(d, 'name') || '?')) {
          c += profile.crossings * R.crossing_cost_m;
        }
      }
    }
    return c;
  };
}

export function profileFor(name) {
  const p = model().profiles[name];
  if (!p) throw new RoutingError(`Unknown bike profile '${name}'`);
  return p;
}

// --- bidirectional Dijkstra (networkx algorithm, heap ordered by (distance, insertion count)) ---------------
class Heap {
  constructor() { this.a = []; }
  get size() { return this.a.length; }
  less(i, j) { const x = this.a[i], y = this.a[j]; return x[0] < y[0] || (x[0] === y[0] && x[1] < y[1]); }
  push(item) {
    const a = this.a; a.push(item);
    let i = a.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (!this.less(i, p)) break; [a[i], a[p]] = [a[p], a[i]]; i = p; }
  }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last; let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1; let m = i;
        if (l < a.length && this.less(l, m)) m = l;
        if (r < a.length && this.less(r, m)) m = r;
        if (m === i) break;
        [a[i], a[m]] = [a[m], a[i]]; i = m;
      }
    }
    return top;
  }
}

export function shortestNodes(graph, source, target, cost) {
  const weight = (u, v, edges) => { let best = Infinity; for (const e of edges) best = Math.min(best, cost(e, u, v)); return best; };
  if (source === target) return [source];
  const dists = [new Map(), new Map()], preds = [new Map([[source, null]]), new Map([[target, null]])];
  const seen = [new Map([[source, 0]]), new Map([[target, 0]])];
  const fringe = [new Heap(), new Heap()];
  let c = 0;
  fringe[0].push([0, c++, source]); fringe[1].push([0, c++, target]);
  const neighbors = [graph.succ, graph.pred];
  let finaldist = null, meetnode = null, dir = 1;
  const path = (curr, d) => { const ret = []; while (curr !== null) { ret.push(curr); curr = preds[d].get(curr); } return d === 0 ? ret.reverse() : ret; };
  while (fringe[0].size && fringe[1].size) {
    dir = 1 - dir;
    const [dist, , v] = fringe[dir].pop();
    if (dists[dir].has(v)) continue;
    dists[dir].set(v, dist);
    if (dists[1 - dir].has(v)) return path(meetnode, 0).concat(path(preds[1].get(meetnode), 1));
    for (const [wn, edges] of neighbors[dir][v]) {
      const cst = dir === 0 ? weight(v, wn, edges) : weight(wn, v, edges);
      const vw = dist + cst;
      if (dists[dir].has(wn)) continue;
      if (!seen[dir].has(wn) || vw < seen[dir].get(wn)) {
        seen[dir].set(wn, vw);
        fringe[dir].push([vw, c++, wn]);
        preds[dir].set(wn, v);
        if (seen[1 - dir].has(wn)) {
          const fd = vw + seen[1 - dir].get(wn);
          if (finaldist === null || finaldist > fd) { finaldist = fd; meetnode = wn; }
        }
      }
    }
  }
  throw new RoutingError('No rideable path between these points');
}

// cheapest parallel edge between consecutive nodes (first one wins a tie, like Python's min)
export function edgesFromNodes(graph, nodes, cost) {
  const out = [];
  for (let i = 0; i + 1 < nodes.length; i++) {
    const u = nodes[i], v = nodes[i + 1];
    let best = null, bestC = Infinity;
    for (const e of graph.succ[u].get(v)) { const k = cost(e, u, v); if (k < bestC) { bestC = k; best = e; } }
    out.push(best);
  }
  return out;
}

// --- Route -----------------------------------------------------------------------------
export class Route {
  constructor(graph, edges, profile, { kind = 'a_to_b', meta = {}, ctx = null } = {}) {
    Object.assign(this, { graph, edges, profile, kind, meta, ctx });
  }
  get nodes() { return this.edges.length ? [this.edges[0].u, ...this.edges.map(e => e.v)] : []; }
  get lengthM() { return pySum(this.edges.map(d => d.length)); }
  get timeS() {
    if (this.ctx === null) return pySum(this.edges.map(d => d.time_s));
    return pySum(this.edges.map(d => travelTimeS(d, this.ctx)));
  }
  coords() {
    const pts = [];
    for (const d of this.edges) pts.push(...(pts.length ? d.geometry.slice(1) : d.geometry));
    return pts;
  }
  elevationProfile() {
    const out = [];
    let dist = 0;
    for (const d of this.edges) {
      const prof = d.elev_profile || [], n = prof.length;
      prof.forEach((z, i) => { if (!(out.length && i === 0)) out.push([dist + d.length * i / Math.max(n - 1, 1), z]); });
      dist += d.length;
    }
    return out;
  }
  edgeSet() { return new Set(this.edges.map(e => ukey(e.u, e.v))); }
}

export function overlap(a, b) {
  const ea = a.edgeSet(), eb = b.edgeSet();
  let inter = 0;
  for (const k of ea) if (eb.has(k)) inter++;
  return inter / Math.max(ea.size + eb.size - inter, 1);
}

// --- Router --------------------------------------------------------------------------------
export class Router {
  constructor(graph) { this.graph = graph; }

  snap(lat, lon) {
    const [node, dist] = nearestNode(this.graph.lats, this.graph.lons, lat, lon);
    if (dist > model().routing.max_snap_m) {
      throw new RoutingError(`Point (${pyFixed(lat, 5)}, ${pyFixed(lon, 5)}) is ${pyFixed(dist, 0)} m from the nearest rideable street - outside the mapped region?`);
    }
    return node;
  }

  legs(stops, cost) {
    let edges = [];
    for (let i = 0; i + 1 < stops.length; i++) {
      edges = edges.concat(edgesFromNodes(this.graph, shortestNodes(this.graph, stops[i], stops[i + 1], cost), cost));
    }
    return edges;
  }

  route(start, end, name = 'balanced', via = [], ctx = null, profile = null) {
    const cost = makeCost(profile || profileFor(name), null, this.graph, ctx);
    let stops = [start, ...via, end].map(p => this.snap(...p));
    stops = stops.filter((n, i) => i === 0 || n !== stops[i - 1]);
    if (stops.length < 2) throw new RoutingError('Start and end are the same point');
    const r = new Route(this.graph, this.legs(stops, cost), name, { ctx });
    if (via.length) r.meta.via = via.map(p => [...p]);
    return r;
  }

  familyRoute(start, end, via = [], ctx = null, fastestM = null) {
    let route = this.route(start, end, 'family', via, ctx);
    fastestM = fastestM || this.route(start, end, 'fastest', via, ctx).lengthM;
    if (route.lengthM > model().routing.family_max_detour * fastestM) {
      const detoured = route.lengthM;
      const cost = makeCost(model().relaxed_family, null, this.graph, ctx);
      const stops = [start, ...via, end].map(p => this.snap(...p));
      let edges = [];
      for (let i = 0; i + 1 < stops.length; i++) {
        if (stops[i] !== stops[i + 1]) edges = edges.concat(edgesFromNodes(this.graph, shortestNodes(this.graph, stops[i], stops[i + 1], cost), cost));
      }
      route = new Route(this.graph, edges, 'family', { ctx });
      route.meta.notice = `A fully low-stress route would be ${pyFixed(detoured / 1000, 1)} km `
        + `(${pyFixed(detoured / fastestM, 1)}x the direct route), so this one `
        + 'uses short busier sections - take extra care on red stretches.';
    }
    return route;
  }

  alternatives(start, end, { profiles = null, maxOverlap = null, via = [], ctx = null } = {}) {
    maxOverlap = maxOverlap ?? model().routing.max_overlap;
    const routes = [];
    let fastestM = null;
    for (const name of profiles || Object.keys(model().profiles)) {
      const r = name === 'family' ? this.familyRoute(start, end, via, ctx, fastestM) : this.route(start, end, name, via, ctx);
      if (name === 'fastest' || name === 'commute') fastestM = r.lengthM;
      const dup = routes.find(o => overlap(o, r) >= maxOverlap);
      if (dup) (dup.meta.also_matches = dup.meta.also_matches || []).push(name);
      else routes.push(r);
    }
    return routes;
  }
}
