// OSM tag helpers: port of cycleroutes/scoring/tags.py. Edge objects carry raw tags (string or list of strings,
// as on simplified osmnx edges). Tables come from the model exported by cycleroutes/web/model.py (setModel).

let M = null;
export function setTagModel(model) { M = model; }

export function values(edge, key) {
  const raw = edge[key];
  if (raw === undefined || raw === null || (typeof raw === 'number' && Number.isNaN(raw))) return [];
  const items = Array.isArray(raw) ? raw : [raw];
  return items.filter(v => v !== null && v !== undefined).map(v => String(v).trim().toLowerCase());
}

export function first(edge, key, dflt = '') {
  const v = values(edge, key);
  return v.length ? v[0] : dflt;
}

export function highway(edge) {
  const hw = values(edge, 'highway').map(h => h.replace('_link', ''));
  for (const cls of M.tags.highway_order) if (hw.includes(cls)) return cls;
  return hw.length ? hw[0] : 'road';
}

// '30 mph' -> 48.27, '50' -> 50, 'none' -> null
export function parseSpeedKmh(value) {
  const m = /^\s*(\d+(?:\.\d+)?)\s*(mph|km\/h|kmh)?/.exec(value);
  if (!m) return null;
  const speed = parseFloat(m[1]);
  return m[2] === 'mph' ? speed * 1.609 : speed;
}

export function speedLimitKmh(edge) {
  const speeds = values(edge, 'maxspeed').map(parseSpeedKmh).filter(s => s);
  if (speeds.length) return Math.max(...speeds);
  return M.tags.default_speed_kmh[highway(edge)] ?? 40;
}

const PY_FLOAT = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
export function lanes(edge) {
  const nums = [];
  for (const v of values(edge, 'lanes')) {
    const s = v.split(';')[0].trim();
    if (PY_FLOAT.test(s)) nums.push(Math.trunc(Number(s)));
  }
  if (nums.length) return Math.max(...nums);
  return ['trunk', 'primary'].includes(highway(edge)) ? 4 : 2;
}

// 'track' (separated), 'lane' (painted), 'shared' or '' (none)
export function cyclewayKind(edge) {
  let vals = [];
  for (const key of ['cycleway', 'cycleway:both', 'cycleway:left', 'cycleway:right']) vals = vals.concat(values(edge, key));
  if (vals.some(v => ['track', 'separate', 'opposite_track'].includes(v))) return 'track';
  if (vals.some(v => ['lane', 'opposite_lane', 'buffered_lane'].includes(v))) return 'lane';
  if (vals.some(v => ['shared_lane', 'share_busway', 'shared'].includes(v))) return 'shared';
  return '';
}

export const isYes = (edge, key) => values(edge, key).some(v => !['no', 'false', '0', ''].includes(v));

export function mtbScale(edge) {
  for (const v of values(edge, 'mtb:scale')) {
    const digits = [...v].filter(ch => ch >= '0' && ch <= '9').join('');
    if (digits) return parseInt(digits[0], 10);
  }
  return null;
}

export function isTrail(edge) {
  const hw = highway(edge);
  if (mtbScale(edge) !== null) return true;
  if (['path', 'track', 'bridleway'].includes(hw)) return true;
  if (hw === 'footway') return !values(edge, 'footway').some(v => v === 'sidewalk' || v === 'crossing');
  if (hw === 'cycleway') {
    const name = values(edge, 'name').join(' ');
    return M.tags.trail_words.some(w => name.includes(w));
  }
  return false;
}

export function hasBikeInfra(edge) {
  if (highway(edge) === 'cycleway' || ['lane', 'track'].includes(cyclewayKind(edge))) return true;
  if (isTrail(edge) && values(edge, 'bicycle').some(v => ['yes', 'designated', 'permissive'].includes(v))) return true;
  if (['path', 'track'].includes(highway(edge)) && !values(edge, 'bicycle').length) return true;
  const facility = String(edge.city_facility || '').toLowerCase();
  return M.tags.city_infra.some(w => facility.includes(w));
}
