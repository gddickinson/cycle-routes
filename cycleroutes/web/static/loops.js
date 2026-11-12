// Round trips of a target distance: port of cycleroutes/routing/loops.py.
// For several compass bearings: start -> A -> B -> start as a rough equilateral triangle, re-riding an edge
// already used in the loop costs extra, and loops are ranked by the profile's headline rating.
import { model } from './scoring_engine.js';
import { destination, nearestNode, pyRound } from './geo.js';
import { Route, RoutingError, edgesFromNodes, makeCost, overlap, profileFor, shortestNodes, ukey } from './router_engine.js';
import { rate } from './rating.js';

function loopForBearing(router, startNode, bearing, sideM, name, ctx) {
  const g = router.graph;
  const slat = g.lats[startNode], slon = g.lons[startNode];
  const a = nearestNode(g.lats, g.lons, ...destination(slat, slon, bearing, sideM))[0];
  const b = nearestNode(g.lats, g.lons, ...destination(slat, slon, bearing + 60, sideM))[0];
  if (new Set([startNode, a, b]).size < 3) throw new RoutingError('Waypoints collapsed onto the start');
  const prof = profileFor(name);
  const penalties = new Map();
  let edges = [];
  for (const [u, v] of [[startNode, a], [a, b], [b, startNode]]) {
    const cost = makeCost(prof, new Map(penalties), g, ctx);
    const leg = edgesFromNodes(g, shortestNodes(g, u, v, cost), cost);
    edges = edges.concat(leg);
    for (const e of leg) penalties.set(ukey(e.u, e.v), model().loops.reuse_penalty);
  }
  return new Route(g, edges, name, { kind: 'loop', ctx });
}

export function reuseFraction(route) {
  const seen = new Set();
  let reused = 0;
  for (const d of route.edges) {
    const k = ukey(d.u, d.v);
    if (seen.has(k)) reused += d.length;
    seen.add(k);
  }
  return reused / Math.max(route.lengthM, 1);
}

export function generateLoops(router, start, distanceKm, name = 'scenic', count = 3, ctx = null) {
  const L = model().loops;
  const startNode = router.snap(...start);
  const sideM = distanceKm * 1000 / (3 * L.detour_factor);
  const key = L.rating_key[name] ?? 'overall';
  const candidates = [];
  for (let i = 0; i < L.bearings; i++) {
    let loop;
    try {
      loop = loopForBearing(router, startNode, i * 360 / L.bearings, sideM, name, ctx);
    } catch (e) {
      if (e instanceof RoutingError) continue;
      throw e;
    }
    loop.meta.target_km = distanceKm;
    const stats = rate(loop);
    const err = Math.abs(stats.distance_km - distanceKm) / distanceKm;
    const reuse = reuseFraction(loop);
    stats.distance_error_pct = pyRound(100 * err, 1);
    stats.reuse_pct = pyRound(100 * reuse, 1);
    const score = (stats.ratings[key] ?? stats.ratings.overall) + 0.5 * stats.ratings.overall - 10 * err - 5 * reuse;
    candidates.push([score, err, loop, stats]);
  }
  candidates.sort((x, y) => y[0] - x[0]);
  let within = candidates.filter(c => c[1] <= L.tolerance);
  if (!within.length) within = candidates;
  const chosen = [];
  for (const [, , loop, stats] of within) {
    if (chosen.every(([other]) => overlap(loop, other) < 0.5)) chosen.push([loop, stats]);
    if (chosen.length === count) break;
  }
  if (!chosen.length) throw new RoutingError('Could not build a loop here - try another start or distance');
  return chosen;
}
