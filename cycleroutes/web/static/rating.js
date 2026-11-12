// Route ratings: port of cycleroutes/routing/rating.py (0-10 per factor, 10 = best, plus summary facts).
import * as tags from './osm_tags.js';
import { model } from './scoring_engine.js';
import { avoided, describe } from './context.js';
import { pairwiseSum, pyRound, pySum } from './geo.js';

function weighted(route, key, dflt) {
  const lengths = route.edges.map(d => d.length);
  const vals = route.edges.map(d => (dflt === undefined ? d[key] : (d[key] ?? dflt)));
  const prod = lengths.map((l, i) => l * vals[i]);
  return pairwiseSum(prod) / Math.max(pairwiseSum(lengths), 1);
}

export function maxGradePct(profile) {
  if (profile.length < 2) return 0.0;
  const run = model().rating.min_grade_run_m;
  let best = 0.0, j = 0;
  for (let i = 0; i < profile.length; i++) {
    while (j < profile.length && profile[j][0] - profile[i][0] < run) j++;
    if (j >= profile.length) break;
    best = Math.max(best, (profile[j][1] - profile[i][1]) / (profile[j][0] - profile[i][0]));
  }
  return pyRound(100 * best, 1);
}

export function hillLabel(c) {
  if (c < 5) return 'Flat';
  if (c < 12) return 'Rolling';
  if (c < 25) return 'Hilly';
  return 'Very hilly';
}

const clamp10 = x => pyRound(Math.min(Math.max(x, 0), 10), 1);
const pct = (x, length) => pyRound(100 * x / Math.max(length, 1), 1);

export function rate(route, fastestTimeS = null) {
  const length = route.lengthM, timeS = route.timeS, E = route.edges;
  const km = Math.max(length / 1000, 0.01);
  const ascent = pySum(E.map(d => d.ascent ?? 0));
  const descent = pySum(E.map(d => d.descent ?? 0));
  const ltsShare = { 1: 0, 2: 0, 3: 0, 4: 0 };
  let infra = 0, signed = 0, trail = 0, avoidedM = 0;
  const ctx = route.ctx;
  const useAvoid = ctx !== null && ctx.avoid && ctx.avoid.length > 0;
  for (const d of E) {
    ltsShare[d.lts] += d.length;
    if (d.bike_infra ?? tags.hasBikeInfra(d)) infra += d.length;
    if (d.trail) trail += d.length;
    if (useAvoid && avoided(ctx, d)) avoidedM += d.length;
    if ((d.route_rank ?? 0) > 0) signed += d.length;
  }
  const ltsPct = {};
  for (const k of [1, 2, 3, 4]) ltsPct[k] = pct(ltsShare[k], length);
  const climbPerKm = ascent / km;
  const avgKmh = (length / 1000) / Math.max(timeS / 3600, 1e-6);
  const baseKmh = route.graph.base_kmh ?? model().scores.base_kmh;
  const speed = fastestTimeS ? 10 * fastestTimeS / Math.max(timeS, 1) : (avgKmh - baseKmh / 2) / (baseKmh / 2) * 10;

  const crashes = pySum(E.map(d => d.crashes ?? 0));
  const severe = pySum(E.map(d => d.crashes_severe ?? 0));
  const nodes = route.graph.nodes;
  let crossings = 0;
  for (const d of E) {
    const nd = nodes[d.v];
    if (nd.risky_crossing && d.lts <= 2 && !nd.busy_names.includes(tags.first(d, 'name') || '?')) crossings++;
  }
  const measured = pySum(E.filter(d => d.aadt).map(d => d.length));
  const busiest = E.reduce((m, d) => Math.max(m, d.aadt ?? 0), 0);
  const hasNoise = E.some(d => 'noise_db' in d), hasShade = E.some(d => 'shade' in d);
  const crossingPenalty = Math.min(2.0, 0.25 * crossings);

  const r = {
    safety: clamp10(10 * weighted(route, 'safety') - crossingPenalty),
    fun: clamp10(10 * weighted(route, 'fun')),
    traffic: clamp10(10 * weighted(route, 'quiet')),
    hills: clamp10(10 - climbPerKm / 2.5),
    speed: clamp10(speed),
    surface: clamp10(10 * weighted(route, 'surface_q')),
  };
  if (hasShade) r.shade = clamp10(10 * weighted(route, 'shade', 0.3));
  r.overall = clamp10(0.3 * r.safety + 0.2 * r.fun + 0.15 * r.traffic + 0.1 * r.hills + 0.15 * r.speed + 0.1 * r.surface);

  const routeNames = [...new Set(E.flatMap(d => d.route_names || []))].sort();
  const mtb = E.filter(d => d.mtb_scale !== null && d.mtb_scale !== undefined).map(d => d.mtb_scale);
  return {
    distance_km: pyRound(length / 1000, 2),
    duration_min: pyRound(timeS / 60, 1),
    avg_speed_kmh: pyRound(avgKmh, 1),
    ascent_m: pyRound(ascent, 0),
    descent_m: pyRound(descent, 0),
    max_grade_pct: maxGradePct(route.elevationProfile()),
    hill_label: hillLabel(climbPerKm),
    lts_pct: ltsPct,
    bike_infra_pct: pct(infra, length),
    signed_route_pct: pct(signed, length),
    signed_routes: routeNames.slice(0, 6),
    scenic_pct: pyRound(100 * weighted(route, 'scenic'), 1),
    ratings: r,
    trail_pct: pct(trail, length),
    max_mtb_scale: mtb.length ? Math.max(...mtb) : null,
    avoided_km: useAvoid ? pyRound(avoidedM / 1000, 2) : null,
    crashes, crashes_severe: severe, risky_crossings: crossings,
    measured_traffic_pct: pct(measured, length),
    busiest_aadt: Math.trunc(busiest) || null,
    avg_noise_db: hasNoise ? pyRound(weighted(route, 'noise_db', 45.0), 1) : null,
    notice: route.meta.notice ?? null,
    context: ctx !== null ? describe(ctx) : [],
  };
}
