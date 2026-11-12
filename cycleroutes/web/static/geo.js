// Spherical geometry and Python-compatible number helpers (port of cycleroutes/routing/geo.py).
// pyRound copies Python's round() (exact value, ties to even) and pairwiseSum copies numpy's float sum,
// so ratings computed here match the Python ones digit for digit.

export const EARTH_RADIUS_M = 6371000.0;
const rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI;

export function haversineM(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2), dphi = p2 - p1, dl = rad(lon2 - lon1);
  const a = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

export function bearingDeg(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1), p2 = rad(lat2), dl = rad(lon2 - lon1);
  const x = Math.sin(dl) * Math.cos(p2);
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return pyMod(deg(Math.atan2(x, y)) + 360, 360);
}

export function destination(lat, lon, bearing, distM) {
  const d = distM / EARTH_RADIUS_M, b = rad(bearing), p1 = rad(lat), l1 = rad(lon);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [deg(p2), deg(l2)];
}

export const compassWord = b => ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest'][pyMod(pyRound(b / 45, 0), 8)];
export const compass = b => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][pyMod(pyRound(b / 45, 0), 8)];

// Python's % (result has the sign of the divisor).
export const pyMod = (a, n) => ((a % n) + n) % n;

// Python round(x, nd): decided on the exact binary value, exact ties go to the even digit.
export function pyRound(x, nd = 0) {
  if (!Number.isFinite(x)) return x;
  const exact = Math.abs(x).toFixed(Math.min(nd + 30, 100));
  const dot = exact.indexOf('.');
  const tail = exact.slice(dot + 1 + nd);
  let out;
  if (/^50*$/.test(tail)) {             // exact tie: keep the even neighbour
    const kept = exact.slice(0, dot + 1 + nd).replace(/\.$/, '');
    const lastDigit = +kept.replace('.', '').slice(-1);
    const unit = 10 ** -nd;
    out = lastDigit % 2 === 0 ? +kept : +kept + unit;
    out = +out.toFixed(nd);
  } else {
    out = +Math.abs(x).toFixed(nd);
  }
  return x < 0 ? -out : out;
}

// Python's '{:.Nf}'.format(x)
export const pyFixed = (x, nd) => pyRound(x, nd).toFixed(nd);

// numpy's pairwise summation (what ndarray.sum() does for float64), so weighted means agree exactly.
export function pairwiseSum(a, start = 0, n = a.length) {
  if (n < 8) {
    let res = 0;
    for (let i = 0; i < n; i++) res += a[start + i];
    return res;
  }
  if (n <= 128) {
    const r = a.slice(start, start + 8);
    let i = 8;
    for (; i < n - (n % 8); i += 8) for (let j = 0; j < 8; j++) r[j] += a[start + i + j];
    let res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
    for (; i < n; i++) res += a[start + i];
    return res;
  }
  let n2 = Math.floor(n / 2);
  n2 -= n2 % 8;
  return pairwiseSum(a, start, n2) + pairwiseSum(a, start + n2, n - n2);
}

// Nearest node (brute force like NodeIndex): [index, distance m]
export function nearestNode(lats, lons, lat, lon) {
  let best = -1, bestD = Infinity;
  for (let i = 0; i < lats.length; i++) {
    const d = haversineM(lat, lon, lats[i], lons[i]);
    if (d < bestD) { bestD = d; best = i; }
  }
  return [best, bestD];
}

// Python's built-in sum() of floats (3.12+: Neumaier compensated summation, as CPython implements it).
export function pySum(values) {
  let s = 0.0, c = 0.0;
  for (const x of values) {
    const t = s + x;
    if (Math.abs(s) >= Math.abs(x)) c += (s - t) + x; else c += (x - t) + s;
    s = t;
  }
  return c && Number.isFinite(c) ? s + c : s;
}
