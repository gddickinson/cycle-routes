// Node test: the JS engine must reproduce the Python results in tests/fixtures/engine_parity.json
// (written by scripts/make_engine_fixtures.py from the committed demo area). Run: node engine.test.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { buildGraph, edgeAt } from './demo_graph.js';
import { scoreEdge } from './scoring_engine.js';
import { Router } from './router_engine.js';
import { makeContext } from './context.js';
import { rate } from './rating.js';
import { generateLoops } from './loops.js';
import { cueSheet } from './directions.js';
import { pyRound, pairwiseSum, pySum } from './geo.js';
import { statDiffs } from './compare.js';

const here = dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(readFileSync(join(here, '../../../tests/fixtures/engine_parity.json'), 'utf8'));
const demo = JSON.parse(readFileSync(join(here, '../demo/prospect_park.json'), 'utf8'));
const M = fx.model;
let checks = 0;
const close = (a, b, what, tol = 1e-9) => {
  checks++;
  if (typeof a === 'number' && typeof b === 'number') {
    assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${what}: JS ${a} vs Python ${b}`);
  } else assert.deepEqual(a, b, what);
};

// Python round() and numpy sums
for (const [x, d, want] of fx.round_cases) close(pyRound(x, d), want, `round(${x}, ${d})`, 0);
for (const [arr, want] of fx.sum_cases) close(pairwiseSum(arr), want, `numpy sum of ${arr.length}`, 0);
for (const [arr, want] of fx.pysum_cases) close(pySum(arr), want, `Python sum of ${arr.length}`, 0);

// graph and per-edge scores
const g = buildGraph(demo, M);
close(g.lats.length, fx.node_count, 'node count');
close(g.edges.length, fx.edge_count, 'edge count');
for (const row of fx.edge_scores) {
  const e = edgeAt(g, ...row.uvk);
  for (const [k, v] of Object.entries(row)) if (k !== 'uvk') close(e[k], v, `edge ${row.uvk} ${k}`);
}
for (const c of fx.synthetic) {
  const e = scoreEdge({ ...c.edge, geometry: [[-73.97, 40.66], [-73.969, 40.661]] });
  for (const [k, v] of Object.entries(c.py)) close(e[k], v, `tags ${JSON.stringify(c.edge)} ${k}`);
}
const risky = {};
g.nodes.forEach((nd, i) => { if (nd.risky_crossing) risky[i] = nd.busy_names; });
close(risky, fx.risky, 'risky crossings');

// routes: same streets, same ratings, same cue sheets
const router = new Router(g);
const sameRoutes = (js, py, what) => {
  close(js.length, py.length, `${what}: number of routes`);
  js.forEach(({ r, stats }, i) => {
    close(r.profile, py[i].profile, `${what} #${i} profile`);
    close(r.edges.map(e => [e.u, e.v, e.key]), py[i].edges, `${what} #${i} (${r.profile}) edges`);
    const d = statDiffs(stats, py[i].stats);
    assert.equal(d.length, 0, `${what} #${i} (${r.profile}) stats: ${d.join('; ')}`); checks++;
    const also = (r.meta.also_matches || []).map(p => M.profiles[p].label);
    close(also, py[i].also_best_for, `${what} #${i} also best for`);
    close(JSON.parse(JSON.stringify(cueSheet(r))), py[i].cues, `${what} #${i} cues`, 1e-12);
  });
};
for (const q of fx.routes) {
  const ctx = makeContext(fx.contexts[q.ctx]);
  const rs = router.alternatives(q.start, q.end, { ctx });
  const fastest = Math.min(...rs.map(r => r.timeS));
  sameRoutes(rs.map(r => ({ r, stats: rate(r, fastest) })), q.routes, `A->B ${q.ctx}`);
}
for (const q of fx.loops) {
  const ctx = makeContext(fx.contexts[q.ctx]);
  const ls = generateLoops(router, q.start, q.km, q.profile, 3, ctx).map(([r, stats]) => ({ r, stats }));
  sameRoutes(ls, q.routes, `loop ${q.profile} ${q.km} km ${q.ctx}`);
}
console.log(`engine.test.mjs: ${checks} checks passed (${fx.routes.reduce((s, q) => s + q.routes.length, 0)} routes, `
  + `${fx.loops.reduce((s, q) => s + q.routes.length, 0)} loops, ${fx.edge_scores.length + fx.synthetic.length} scored edges)`);
