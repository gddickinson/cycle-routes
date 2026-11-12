// Compare routes computed in the browser with the Python router's answer for the same request.
import { esc } from './core.js';

// Differences between two stats objects (numbers within 1e-9, everything else exactly).
export function statDiffs(a, b, path = '') {
  const out = [];
  const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
  for (const k of keys) {
    const x = a?.[k], y = b?.[k], p = path ? `${path}.${k}` : k;
    if (x && y && typeof x === 'object' && typeof y === 'object') out.push(...statDiffs(x, y, p));
    else if (typeof x === 'number' && typeof y === 'number') { if (Math.abs(x - y) > 1e-9) out.push(`${p}: ${x} vs ${y}`); }
    else if (JSON.stringify(x ?? null) !== JSON.stringify(y ?? null)) out.push(`${p}: ${JSON.stringify(x)} vs ${JSON.stringify(y)}`);
  }
  return out;
}

const triples = r => r.edges.map(e => [e.u, e.v, e.key].join(',')).join(';');

export function compareRoutes(js, py) {
  const n = Math.max(js.length, py.length);
  let same = 0;
  const notes = [];
  for (let i = 0; i < n; i++) {
    const a = js[i], b = py[i];
    if (!a || !b) { notes.push(`route ${i + 1}: only one side has it`); continue; }
    const pyEdges = b.edges.map(e => e.join(',')).join(';');
    const diffs = statDiffs(a.stats, b.stats);
    if (triples(a.r) === pyEdges && !diffs.length && a.r.profile === b.profile) same++;
    else notes.push(`route ${i + 1} (${b.profile_label}): ${triples(a.r) === pyEdges ? '' : 'different streets; '}${diffs.slice(0, 3).join('; ')}`);
  }
  const ok = same === n && js.length === py.length;
  return `<p class="${ok ? 'ok' : 'warnc'}">${ok ? '✓' : '✗'} Python agrees on ${same} of ${n} route${n === 1 ? '' : 's'}
    (same streets, same ratings).</p>${notes.length ? `<ul>${notes.map(t => `<li>${esc(t)}</li>`).join('')}</ul>` : ''}`;
}
