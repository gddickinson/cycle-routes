// Street scoring: port of cycleroutes/scoring/lts.py, edge_scores.py and edge_attrs.py (add_scores, add_crossings).
// Every table and threshold comes from the exported model (setModel); only the formulas live here.
import * as tags from './osm_tags.js';
import { bearingDeg, pyRound } from './geo.js';

let M = null;
export function setModel(model) { M = model; tags.setTagModel(model); }
export const model = () => M;

const offRoad = () => M.lts.off_road, calm = () => M.lts.calm_streets;

// --- Level of Traffic Stress -------------------------------------------------
export function classify(edge) {
  const hw = tags.highway(edge);
  const { mph25, mph30, mph40 } = M.lts;
  if (offRoad().includes(hw)) return 1;
  if (hw === 'steps') return 2;
  const kind = tags.cyclewayKind(edge);
  if (kind === 'track') return 1;
  const speed = tags.speedLimitKmh(edge), n = tags.lanes(edge);
  if (kind === 'lane') {
    if (speed <= mph30 && n <= 2) return 2;
    if (speed <= mph40 && n <= 4) return 3;
    return 4;
  }
  if (hw === 'living_street') return 1;
  if (calm().includes(hw) && n <= 2) {
    if (speed <= mph25) return 1;
    return speed <= mph30 ? 2 : 3;
  }
  if (speed <= mph25 && n <= 2) return 2;
  if (speed <= mph30 && n <= 2 && hw !== 'primary' && hw !== 'trunk') return 3;
  return 4;
}

export function withMeasuredTraffic(osmLts, edge) {
  const aadt = edge.aadt;
  if (!aadt || offRoad().includes(tags.highway(edge)) || tags.cyclewayKind(edge) === 'track') return osmLts;
  const lane = tags.cyclewayKind(edge) === 'lane';
  if (aadt >= 20000) return Math.max(osmLts, lane ? 3 : 4);
  if (aadt >= 8000) return Math.max(osmLts, lane ? 2 : 3);
  if (aadt < 1500 && osmLts === 2 && !lane) return 1;
  return osmLts;
}

export function effective(edge) {
  let level = withMeasuredTraffic(classify(edge), edge);
  if (edge.city_lts) level = Math.trunc((level + edge.city_lts) / 2 + 0.5);
  return level;
}

// --- 0-1 scores ---------------------------------------------------------------
const clamp01 = x => Math.min(Math.max(x, 0), 1);

export function safety(edge) {
  let s = M.scores.lts_safety[edge.lts];
  s -= Math.min(0.35, 0.06 * (edge.crashes ?? 0) + 0.12 * (edge.crashes_severe ?? 0));
  if (tags.first(edge, 'lit') === 'yes') s += 0.05;
  if ((edge.route_rank ?? 0) > 0) s += 0.05;
  return Math.min(Math.max(s, 0), 1);
}

export function quietness(edge) {
  let s;
  if (edge.aadt) {
    s = clamp01(1 - (Math.log10(edge.aadt) - 2) / (Math.log10(40000) - 2));
  } else {
    s = M.scores.quiet_by_highway[tags.highway(edge)] ?? 0.6;
    if (tags.lanes(edge) >= 4) s *= 0.6;
  }
  if (tags.cyclewayKind(edge) === 'track' || offRoad().includes(tags.highway(edge))) s = Math.max(s, 0.8);
  const db = edge.noise_db;
  if (db) s = 0.75 * s + 0.25 * Math.min(Math.max((72 - db) / 30, 0), 1);
  return s;
}

export function surface(edge) {
  const sq = M.scores.surface_quality;
  const known = tags.values(edge, 'surface').filter(s => s in sq).map(s => sq[s]);
  const scale = tags.mtbScale(edge);
  if (scale !== null && scale >= 2) known.push(0.3);
  if (known.length) return Math.min(...known);
  const hw = tags.highway(edge);
  if (hw === 'track' || hw === 'bridleway') return 0.45;
  if (hw === 'path' || hw === 'footway') return 0.7;
  return 1.0;
}

export function fun(edge) {
  const greenway = offRoad().includes(tags.highway(edge)) || tags.isTrail(edge) ? 1.0 : 0.0;
  const route = Math.min(edge.route_rank ?? 0, 2) / 2;
  const shade = edge.shade ?? 0.3;
  return 0.38 * (edge.scenic ?? 0) + 0.22 * quietness(edge) + 0.15 * Math.max(greenway, route)
    + 0.12 * surface(edge) + 0.13 * shade;
}

export function speedKmh(edge) {
  const length = Math.max(edge.length, 1.0);
  const grade = ((edge.ascent ?? 0) - (edge.descent ?? 0)) / length;
  let base = M.scores.base_kmh * (0.6 + 0.4 * surface(edge));
  const hw = tags.highway(edge);
  if (hw === 'steps') return 3.0;
  if (hw === 'footway' || hw === 'pedestrian') base = Math.min(base, 12.0);
  const scale = tags.mtbScale(edge);
  if (scale !== null && scale >= 1) base = Math.min(base, Math.max(16.0 - 3.0 * scale, 6.0));
  for (const s of tags.values(edge, 'service')) {
    if (s in M.scores.awkward_service) base = Math.min(base, M.scores.awkward_service[s][0]);
  }
  if (grade > 0) return Math.max(base / (1 + 12 * grade), 5.0);
  return Math.min(base * (1 + 4 * -grade), M.scores.max_downhill_kmh);
}

export function awkwardness(edge) {
  const m = tags.values(edge, 'service').filter(s => s in M.scores.awkward_service).map(s => M.scores.awkward_service[s][1]);
  return m.length ? Math.max(...m) : 1.0;
}

export const travelTimeS = edge => edge.length / (speedKmh(edge) / 3.6);

const ENHANCED = ['city_lts', 'city_facility', 'aadt', 'crashes', 'crashes_severe', 'noise_db', 'shade'];

// All derived attributes of one edge (add_scores for a single edge); signalAtEnd adds the signal delay.
export function scoreEdge(data, signalAtEnd = false) {
  const g = data.geometry;
  if (g && g.length) {
    const [x0, y0] = g[0], [x1, y1] = g[g.length - 1];
    data.bearing = pyRound(bearingDeg(y0, x0, y1, x1), 1);
  }
  data.trail = tags.isTrail(data);
  data.mtb_scale = tags.mtbScale(data);
  data.bike_infra = tags.hasBikeInfra(data);
  data.lts_osm = classify(data);
  data.lts = effective(data);
  data.safety = safety(data);
  data.quiet = quietness(data);
  data.surface_q = surface(data);
  data.fun = fun(data);
  data.time_s = travelTimeS(data);
  const base = {};
  for (const [k, v] of Object.entries(data)) if (!ENHANCED.includes(k)) base[k] = v;
  base.lts = data.lts_osm;
  data.safety_osm = safety(base);
  data.quiet_osm = quietness(base);
  data.fun_osm = fun(base);
  data.awkward = awkwardness(data);
  if (signalAtEnd) data.time_s += M.scores.signal_delay_s;
  return data;
}

// add_crossings: junctions where a low-stress street meets an LTS 3-4 road without signals.
// Mirrors networkx's undirected view of a MultiDiGraph: one entry per (neighbour, key), out-edge data first.
export function addCrossings(graph) {
  let n = 0;
  graph.nodes.forEach((nd, node) => {
    const seen = new Map();
    for (const e of graph.out[node]) { const k = e.v + '|' + e.key; if (!seen.has(k)) seen.set(k, e); }
    for (const e of graph.inn[node]) { const k = e.u + '|' + e.key; if (!seen.has(k)) seen.set(k, e); }
    const busy = new Set();
    let calmSeen = false, degree = 0;
    for (const [k, d] of seen) {
      degree += +k.split('|')[0] === node ? 2 : 1;      // self-loops count twice
      if ((d.lts ?? 1) >= 3) busy.add(tags.first(d, 'name') || '?'); else calmSeen = true;
    }
    const risky = !nd.signals && busy.size > 0 && calmSeen && degree >= 3;
    nd.risky_crossing = risky;
    nd.busy_names = risky ? [...busy].sort() : [];
    n += risky ? 1 : 0;
  });
  return n;
}
