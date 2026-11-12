// Riding context: port of cycleroutes/routing/context.py (bike type, darkness, wind, heat, avoid, bike-lanes-only).
// Closures and community reports are live data in the local app; here they are empty sets the cost still honours.
import * as tags from './osm_tags.js';
import { model, surface as surfaceScore, speedKmh } from './scoring_engine.js';
import { compass, pyFixed } from './geo.js';

export function makeContext(opts = {}) {
  return {
    bike: 'hybrid', dark: false, wind_kmh: 0, wind_from_deg: 0, hot: false,
    closed: new Set(), restricted: new Set(), edge_multipliers: new Map(),
    avoid: [], infra_only: false, prefer: '', osm_only: false, ...opts,
  };
}

export const bikeType = ctx => model().bike_types[ctx.bike] || model().bike_types.hybrid;

function busy(e) {
  if (e.aadt) return e.aadt > 10000;
  const hw = tags.highway(e);
  return hw === 'trunk' || hw === 'primary' || (hw === 'secondary' && tags.lanes(e) >= 4);
}
const isProtected = e => tags.cyclewayKind(e) === 'track' || tags.highway(e) === 'cycleway'
  || String(e.city_facility || '').toLowerCase().includes('protected');
const inTraffic = pred => e => pred(e) && !isProtected(e);

export const AVOID_PREDICATES = {
  major: inTraffic(e => ['trunk', 'primary'].includes(tags.highway(e))),
  secondary: inTraffic(e => tags.highway(e) === 'secondary'),
  busy: inTraffic(busy),
  stressful: e => (e.lts ?? 1) >= 3,
  unpaved: e => (e.surface_q ?? 1.0) < 0.6,
  steps: e => tags.highway(e) === 'steps',
  sidewalks: e => ['footway', 'pedestrian'].includes(tags.highway(e)) && !(e.trail ?? false),
  service: e => tags.highway(e) === 'service',
  trails: e => e.trail ?? false,
};

export const avoided = (ctx, edge) => ctx.avoid.some(k => AVOID_PREDICATES[k] && AVOID_PREDICATES[k](edge));

export function describe(ctx) {
  const notes = [];
  const bt = bikeType(ctx);
  if (ctx.bike !== 'hybrid') notes.push(bt.label);
  if (ctx.dark) notes.push('after dark: lit streets preferred');
  if (ctx.wind_kmh >= 12) notes.push(`wind ${pyFixed(ctx.wind_kmh, 0)} km/h from ${compass(ctx.wind_from_deg)}`);
  if (ctx.hot) notes.push('hot: shade preferred');
  if (ctx.closed.size || ctx.restricted.size) notes.push(`${ctx.closed.size} closures avoided`);
  if (ctx.avoid.length) {
    const labels = model().avoid_types;
    notes.push('avoiding ' + [...ctx.avoid].sort().filter(k => k in labels)
      .map(k => labels[k].split(' (')[0].toLowerCase()).join(', '));
  }
  if (ctx.infra_only) notes.push('bike lanes & trails only where possible');
  if (ctx.osm_only) notes.push('scored with OpenStreetMap only');
  return notes;
}

export function headwindKmh(edge, ctx) {
  if (ctx.wind_kmh <= 0 || edge.bearing === undefined) return 0;
  return ctx.wind_kmh * Math.cos((edge.bearing - ctx.wind_from_deg) * Math.PI / 180);
}

export function travelTimeS(edge, ctx) {
  const bt = bikeType(ctx);
  if (bt.label === model().bike_types.hybrid.label && ctx.wind_kmh === 0) return edge.time_s;
  const length = Math.max(edge.length, 1.0);
  const grade = ((edge.ascent ?? 0) - (edge.descent ?? 0)) / length;
  let base = bt.speed_kmh * (0.6 + 0.4 * surfaceScore(edge)) - 0.3 * headwindKmh(edge, ctx);
  base = Math.max(base, 6.0);
  if (tags.highway(edge) === 'steps') return length / (2 / 3.6) + 30;
  const speed = grade > 0 ? Math.max(base / (1 + bt.climb_factor * grade), 5.0)
    : Math.min(base * (1 + 4 * -grade), model().scores.max_downhill_kmh);
  const extra = edge.time_s - edge.length / (speedKmh(edge) / 3.6);
  return length / (speed / 3.6) + Math.max(extra, 0);
}

export function edgeMultiplier(edge, key, ctx, safetyWeight) {
  const bt = bikeType(ctx), R = model().routing;
  let m = 1.0;
  const surf = edge.surface_q ?? 1.0;
  if (bt.min_surface && surf < bt.min_surface) m *= 4.0;
  if (bt.rough_bonus && surf < 0.6) m *= 0.8;
  const hw = tags.highway(edge);
  if (hw === 'steps') m *= bt.steps_penalty;
  if (hw === 'footway' || hw === 'pedestrian') m *= bt.footway_penalty;
  m *= bt.extra_lts_penalty[edge.lts] ?? 1.0;
  if (ctx.dark && tags.first(edge, 'lit') !== 'yes') {
    const offRoad = ['path', 'footway', 'track', 'cycleway', 'bridleway'].includes(hw);
    m *= 1 + (offRoad ? 0.5 : 0.2) * Math.min(safetyWeight, 4) / 2;
  }
  if (ctx.hot) m *= 1 + 0.6 * (1 - (edge.shade ?? 0.3));
  const hwk = headwindKmh(edge, ctx);
  if (hwk > 0) m *= 1 + 0.015 * hwk;
  if (ctx.avoid.length && avoided(ctx, edge)) m *= R.avoid_penalty;
  if (ctx.infra_only && !(edge.bike_infra ?? false)) m *= R.infra_only_penalty;
  const P = R.prefer_penalty, trail = edge.trail ?? false;
  if (ctx.prefer === 'trails' && !trail) m *= P.trails;
  else if (ctx.prefer === 'lively') m *= (edge.lively ?? 0) >= 0.3 ? 1.0 : P.lively;
  else if (ctx.prefer === 'sights') m *= edge.sights ? 0.7 : P.sights;
  else if (ctx.prefer === 'nature') m *= (edge.scenic ?? 0) >= 0.3 ? 1.0 : P.nature;
  else if (ctx.prefer === 'accessible' && !(edge.accessible ?? true)) m *= P.accessible;
  else if (ctx.prefer === 'mtb') {
    const rough = trail && ((edge.mtb_scale ?? null) !== null || surf < 0.6);
    m *= rough ? 0.8 : (trail ? 1.0 : P.mtb);
  }
  if (ctx.closed.has(key)) m *= 25.0;
  else if (ctx.restricted.has(key)) m *= 1.3;
  return m * (ctx.edge_multipliers.get(key) ?? 1.0);
}
