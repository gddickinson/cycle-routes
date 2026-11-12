// Street scores: type (or pick) a street's OpenStreetMap tags and see how Cycle Routes scores it, live in the browser
// (JS port of scoring/lts.py + edge_scores.py); the local app can check the same street with the Python code.
import { route, app, api, esc, isStatic, needsServer, $ } from './core.js';
import { engine } from './engine.js';
import { scoreEdge } from './scoring_engine.js';
import { statDiffs } from './compare.js';

const TAG_FIELDS = [
  ['highway', 'select'], ['name', 'text'], ['maxspeed', 'text', 'e.g. 25 mph or 50'], ['lanes', 'text', 'e.g. 2'],
  ['cycleway', 'select', ['', 'lane', 'buffered_lane', 'track', 'shared_lane', 'no']], ['surface', 'select'],
  ['lit', 'select', ['', 'yes', 'no']], ['service', 'select', ['', 'parking_aisle', 'driveway', 'drive-through', 'alley']],
  ['bicycle', 'select', ['', 'yes', 'designated', 'permissive', 'no']], ['footway', 'select', ['', 'sidewalk', 'crossing']],
  ['mtb:scale', 'select', ['', '0', '1', '2', '3', '4']],
];
const NUM_FIELDS = [['length', 'Length (m)', 200], ['ascent', 'Climb (m)', 0], ['descent', 'Descent (m)', 0],
  ['scenic', 'Share near parks / water (0-1)', 0], ['route_rank', 'Signed cycle route (0 none - 4 international)', 0]];
const MEASURED = [['aadt', 'Measured traffic (vehicles/day)'], ['noise_db', 'Noise (dB)'], ['shade', 'Tree shade (0-1)'],
  ['crashes', 'Recorded bike crashes'], ['crashes_severe', 'of which serious']];
const OUT = [['safety', 'Safety'], ['quiet', 'Quiet (traffic)'], ['surface_q', 'Surface'], ['fun', 'Fun']];

function presets(eng) {
  // one real street per highway class / stress level found in the demo area (named ones first)
  const seen = new Map();
  for (const e of eng.draw) {
    const name = Array.isArray(e.name) ? e.name[0] : e.name;
    const k = `${e.highway}|${e.lts}`;
    if (name && !seen.has(k)) seen.set(k, { label: `${name} (${[].concat(e.highway).join('/')}, LTS ${e.lts})`, e });
  }
  return [...seen.values()].sort((a, b) => a.e.lts - b.e.lts).slice(0, 14);
}

route('scoring', async () => {
  const eng = await engine(), M = eng.model;
  const opts = { highway: M.tags.highway_order, surface: [''].concat(Object.keys(M.scores.surface_quality)) };
  const pres = presets(eng);
  const field = ([k, type, extra]) => {
    const id = 'f-' + k.replace(':', '_');
    if (type === 'select') {
      const vals = Array.isArray(extra) ? extra : opts[k];
      return `<div><label for="${id}">${k}</label><select id="${id}" data-tag="${k}">${vals.map(v => `<option value="${v}">${v || '—'}</option>`).join('')}</select></div>`;
    }
    return `<div><label for="${id}">${k}</label><input id="${id}" data-tag="${k}" placeholder="${esc(extra || '')}"></div>`;
  };
  app().innerHTML = `
  <p class="kicker">Scoring · every street, from its OpenStreetMap tags</p>
  <h1>Street scores</h1>
  <p class="lead">Each street segment gets a Level of Traffic Stress (LTS 1-4, a simplified Mekuria/Furth/Nixon (2012)
  method as commonly applied to OSM data) and 0-1 scores for safety, quiet, surface and fun, plus a riding speed from
  gradient and surface. Change the tags and the numbers update; or start from a real street in the demo area.</p>
  <div class="two">
    <form class="panel" id="tagform" onsubmit="return false">
      <label for="preset">Start from a street in the demo area</label>
      <select id="preset"><option value="">—</option>${pres.map((p, i) => `<option value="${i}">${esc(p.label)}</option>`).join('')}</select>
      <h3>OSM tags</h3><div class="fields">${TAG_FIELDS.map(field).join('')}</div>
      <h3>Geometry &amp; enrichment</h3><div class="fields">${NUM_FIELDS.map(([k, l, v]) => `<div><label for="n-${k}">${l}</label><input id="n-${k}" type="number" step="any" data-num="${k}" value="${v}"></div>`).join('')}</div>
      <details><summary>Extra open data (Austin / US layers)</summary><div class="fields">${MEASURED.map(([k, l]) => `<div><label for="m-${k}">${l}</label><input id="m-${k}" type="number" step="any" data-num="${k}" placeholder="none"></div>`).join('')}</div></details>
    </form>
    <div><div class="panel" id="out" aria-live="polite"></div><div id="pyc"></div></div>
  </div>
  <h2>Riding styles</h2>
  <p>A route's cost is its length (or riding time for <i>Fastest</i>) multiplied by <span class="eq">1 + Σ weight × (1 − score)</span>,
  by a penalty for stressful streets, and by the context (bike type, darkness, wind, roads to avoid); climbing and
  unsignalised crossings of busy roads add a fixed cost. The weights below come straight from <code>config.PROFILES</code>.</p>
  <div class="scroll"><table><thead><tr><th>Style</th><th>Safety</th><th>Fun</th><th>Traffic</th><th>Hills</th><th>Surface</th><th>Shade</th><th>Crossings</th><th>Stress penalty</th></tr></thead>
  <tbody>${Object.values(M.profiles).map(p => `<tr><td><b>${esc(p.label)}</b><br><small class="mute">${esc(p.description)}${p.time ? ' (by time)' : ''}${p.prefer ? ` · prefers ${p.prefer}` : ''}</small></td>
    ${['safety', 'fun', 'traffic', 'hills', 'surface', 'shade', 'crossings'].map(k => `<td class="mono">${p[k] || '·'}</td>`).join('')}
    <td class="mono">${Object.entries(p.lts_penalty).map(([l, x]) => `LTS ${l} ×${x}`).join(', ') || '·'}</td></tr>`).join('')}</tbody></table></div>`;

  const read = () => {
    const e = { geometry: [[0, 0], [0, 0.001]] };
    document.querySelectorAll('[data-tag]').forEach(el => { if (el.value.trim()) e[el.dataset.tag] = el.value.trim(); });
    document.querySelectorAll('[data-num]').forEach(el => { if (el.value !== '') e[el.dataset.num] = +el.value; });
    if (!e.highway) e.highway = 'residential';
    e.length = e.length || 1;
    return e;
  };
  function update() {
    const e = scoreEdge(read());
    $('#out').innerHTML = `<div class="ltsbig" style="--lc:${M.lts_colors[e.lts]}"><b>LTS ${e.lts}</b><span>${esc(M.lts_labels[e.lts])}</span></div>
      ${e.lts !== e.lts_osm ? `<p class="small mute">From the OSM tags alone: LTS ${e.lts_osm}; the measured data changes it.</p>` : ''}
      <div class="rates">${OUT.map(([k, l]) => `<div class="rate"><span>${l}</span><i><b style="width:${e[k] * 100}%"></b></i><em>${e[k].toFixed(2)}</em></div>`).join('')}</div>
      <p class="small">Riding time <b>${e.time_s.toFixed(1)} s</b> for ${e.length} m (${(e.length / e.time_s * 3.6).toFixed(1)} km/h on a hybrid)
      · ${e.bike_infra ? 'has bike space' : 'no bike lane or path'} · ${e.trail ? 'off-road trail' : 'not a trail'}${e.awkward > 1 ? ` · awkward ×${e.awkward}` : ''}</p>`;
    $('#pyc').innerHTML = isStatic() ? needsServer('"Check with Python"') : '<button type="button" class="alt" id="pyb">Check with Python</button> <span id="pyo" class="small"></span>';
    if (!isStatic()) $('#pyb').addEventListener('click', () => check(e));
  }
  async function check(e) {
    const body = { tags: {} };
    for (const [k, v] of Object.entries(read())) if (k !== 'geometry') (typeof v === 'number' ? body : body.tags)[k] = v;
    try {
      const py = await api('/score', { body });
      const mine = Object.fromEntries(Object.keys(py).map(k => [k, e[k]]));
      const d = statDiffs(mine, py);
      $('#pyo').innerHTML = d.length ? `<span class="warnc">✗ ${esc(d.join('; '))}</span>` : '<span class="ok">✓ Python gives the same scores</span>';
    } catch (err) { $('#pyo').innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  }
  $('#preset').addEventListener('change', ev => {
    const p = pres[ev.target.value]; if (!p) return;
    document.querySelectorAll('[data-tag]').forEach(el => { const v = p.e[el.dataset.tag]; el.value = v === undefined ? '' : [].concat(v)[0]; });
    for (const k of ['length', 'ascent', 'descent', 'scenic', 'route_rank']) $('#n-' + k).value = +(+p.e[k]).toFixed(4);
    update();
  });
  $('#tagform').addEventListener('input', update);
  update();
});
