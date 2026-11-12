// Turn-by-turn cue sheet: port of cycleroutes/routing/directions.py (with service-road jog merging).
import * as tags from './osm_tags.js';
import { model } from './scoring_engine.js';
import { bearingDeg, compassWord, pyMod, pyRound } from './geo.js';

function streetName(d) {
  const raw = d.name;
  const name = Array.isArray(raw) ? raw[0] : raw;
  if (typeof name === 'string' && name.trim()) return name.trim();
  const hw = tags.highway(d);
  return { cycleway: 'cycle path', path: 'path', footway: 'footpath', track: 'track', service: 'service road' }[hw] || 'unnamed road';
}

function edgeBearings(d) {
  const p = d.geometry, n = p.length;
  return [bearingDeg(p[0][1], p[0][0], p[1][1], p[1][0]), bearingDeg(p[n - 2][1], p[n - 2][0], p[n - 1][1], p[n - 1][0])];
}

export function turnWord(delta) {
  const a = Math.abs(delta), side = delta > 0 ? 'right' : 'left';
  if (a < model().directions.turn_threshold_deg) return 'Continue';
  if (a < 60) return `Bear ${side}`;
  if (a < 135) return `Turn ${side}`;
  return `Sharp ${side}`;
}

const cue = (at_km, instruction, street, lts, lat, lon) => ({ at_km, instruction, street, lts, lat, lon });

export function cueSheet(route) {
  const D = model().directions, data = route.edges, cues = [];
  if (!data.length) return cues;
  const first = data[0];
  let [lon, lat] = first.geometry[0];
  cues.push(cue(0.0, `Start heading ${compassWord(edgeBearings(first)[0])} on ${streetName(first)}`, streetName(first), first.lts, lat, lon));
  let dist = first.length;
  let prevStreet = streetName(first), prevArrival = edgeBearings(first)[1];
  for (const d of data.slice(1)) {
    const street = streetName(d);
    const [leave, arrive] = edgeBearings(d);
    const delta = pyMod(leave - prevArrival + 540, 360) - 180;
    const turning = Math.abs(delta) >= D.turn_threshold_deg;
    if (street !== prevStreet || (turning && Math.abs(delta) >= 60)) {
      [lon, lat] = d.geometry[0];
      const verb = turnWord(delta);
      cues.push(cue(pyRound(dist / 1000, 2), verb !== 'Continue' ? `${verb} onto ${street}` : `Continue onto ${street}`, street, d.lts, lat, lon));
    }
    prevStreet = street; prevArrival = arrive;
    dist += d.length;
  }
  const last = data[data.length - 1].geometry;
  [lon, lat] = last[last.length - 1];
  cues.push(cue(pyRound(dist / 1000, 2), route.kind === 'loop' ? 'Arrive back at start' : 'Arrive at destination', '', data[data.length - 1].lts, lat, lon));
  return mergeSameStreet(cues, D);
}

function mergeSameStreet(cues, D) {
  const out = [];
  for (const c of cues) {
    const prev = out[out.length - 1];
    if (prev && c.street === prev.street) {
      if (c.instruction.startsWith('Continue')) continue;
      if (D.generic_streets.includes(c.street) && c.at_km - prev.at_km < D.jog_merge_km) {
        const verb = prev.instruction.split(' onto ')[0];
        if (verb === 'Continue') prev.instruction = `Follow the ${c.street}`;
        else if (!verb.startsWith('Start') && !verb.startsWith('Follow') && !verb.includes('then follow')) prev.instruction = `${verb}, then follow the ${c.street}`;
        prev.lts = Math.max(prev.lts, c.lts);
        continue;
      }
    }
    out.push(c);
  }
  return out;
}
