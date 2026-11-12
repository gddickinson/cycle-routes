// Plan a ride on the demo area: A->B alternatives (one per riding style) or loops, computed in the browser by the
// JS port of the router; in the local app "Check with Python" asks the Python router for the same request.
import { route, app, api, esc, isStatic, needsServer, onLeave, $ } from './core.js';
import { engine } from './engine.js';
import { MapView } from './map_view.js';
import { makeContext } from './context.js';
import { rate } from './rating.js';
import { generateLoops } from './loops.js';
import { cueSheet } from './directions.js';
import { routeCard, bindCards, cueList, elevationSvg, safetyNote, ROUTE_COLORS } from './route_cards.js';
import { compareRoutes } from './compare.js';

const elevKm = r => r.elevationProfile().map(([d, z]) => [d / 1000, z]);

route('explore', async () => {
  const eng = await engine();
  const M = eng.model, hubs = eng.demo.area.hubs;
  const hubOpts = sel => hubs.map((h, i) => `<option value="${i}"${i === sel ? ' selected' : ''}>${esc(h.name)}</option>`).join('');
  app().innerHTML = `
  <p class="kicker">${esc(eng.demo.area.title)} · demo area</p>
  <h1>Plan a ride</h1>
  <p class="lead">Tap the map to set a start <b class="pa">A</b> and a destination <b class="pb">B</b> (or pick places below).
  Every riding style gets its own route, near-duplicates are merged, and each is rated 0-10, all computed in your browser
  by the JavaScript port of the Python router.</p>
  <div class="plan">
    <form class="panel controls" id="ctl" onsubmit="return false">
      <div class="seg" role="group" aria-label="Kind of ride"><button type="button" data-kind="ab" class="on">A → B</button><button type="button" data-kind="loop">Loop</button></div>
      <div id="abf">
        <label for="pa">Start (A)</label><select id="pa"><option value="">tap the map…</option>${hubOpts(-1)}</select>
        <label for="pb">Destination (B)</label><select id="pb"><option value="">tap the map…</option>${hubOpts(-1)}</select>
      </div>
      <div id="lpf" hidden>
        <label for="ls">Start</label><select id="ls"><option value="">tap the map…</option>${hubOpts(-1)}</select>
        <label for="lkm">Distance <b id="lkmv">5</b> km</label><input type="range" id="lkm" min="2" max="10" step="0.5" value="5">
        <label for="lprof">Riding style</label><select id="lprof">${Object.entries(M.profiles).map(([k, p]) => `<option value="${k}"${k === 'scenic' ? ' selected' : ''}>${esc(p.label)}</option>`).join('')}</select>
      </div>
      <label for="bike">Bike</label><select id="bike">${Object.entries(M.bike_types).map(([k, b]) => `<option value="${k}">${esc(b.label)}</option>`).join('')}</select>
      <label class="chk"><input type="checkbox" id="dark"> After dark (prefer lit streets)</label>
      <label class="chk"><input type="checkbox" id="infra"> Bike lanes, cycle paths &amp; trails only (where possible)</label>
      <details><summary>Avoid…</summary>${Object.entries(M.avoid_types).map(([k, l]) => `<label class="chk"><input type="checkbox" name="avoid" value="${k}"> ${esc(l)}</label>`).join('')}</details>
      <details><summary>Wind</summary>
        <label for="wind">Speed <b id="windv">0</b> km/h</label><input type="range" id="wind" min="0" max="40" step="2" value="0">
        <label for="wdir">From</label><select id="wdir">${['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'].map((d, i) => `<option value="${i * 45}">${d}</option>`).join('')}</select></details>
      <button type="button" id="go">Find routes</button><button type="button" class="alt" id="clear">Clear</button>
      <p class="small mute" id="status" aria-live="polite"></p>
      <div id="pycheck"></div>
    </form>
    <div><div id="map"></div><div class="legend small">${[1, 2, 3, 4].map(k => `<span><i style="background:${M.lts_colors[k]}"></i>LTS ${k}: ${esc(M.lts_labels[k])}</span>`).join('')}</div></div>
  </div>
  <div id="results"></div>
  ${safetyNote(M)}`;

  const st = { kind: 'ab', a: null, b: null, routes: [], sel: 0 };
  const map = new MapView($('#map'), eng, { onPick: (lat, lon) => pick(lat, lon) });
  onLeave(() => map.destroy());

  const markers = () => map.setMarkers([st.a && { ...st.a, label: 'A', color: '#7cff6b' },
    st.kind === 'ab' && st.b && { ...st.b, label: 'B', color: '#ff6fd8' }].filter(Boolean));
  const status = t => { $('#status').textContent = t; };
  function pick(lat, lon) {
    if (st.kind === 'loop' || !st.a || st.b) { st.a = { lat, lon }; if (st.kind === 'ab') st.b = null; }
    else st.b = { lat, lon };
    markers();
    if (st.kind === 'loop' || st.b) plan(); else status('Now tap the destination (B).');
  }
  const fromHub = (sel, key) => $(sel).addEventListener('change', e => {
    const h = hubs[e.target.value]; if (!h) return;
    st[key] = { lat: h.lat, lon: h.lon }; markers();
    if ((st.kind === 'loop') || (st.a && st.b)) plan();
  });
  fromHub('#pa', 'a'); fromHub('#pb', 'b'); fromHub('#ls', 'a');
  document.querySelectorAll('[data-kind]').forEach(b => b.addEventListener('click', () => {
    st.kind = b.dataset.kind;
    document.querySelectorAll('[data-kind]').forEach(x => x.classList.toggle('on', x === b));
    $('#abf').hidden = st.kind !== 'ab'; $('#lpf').hidden = st.kind !== 'loop';
    st.routes = []; render(); markers();
  }));
  $('#lkm').addEventListener('input', e => { $('#lkmv').textContent = e.target.value; });
  $('#wind').addEventListener('input', e => { $('#windv').textContent = e.target.value; });
  $('#go').addEventListener('click', plan);
  $('#clear').addEventListener('click', () => { st.a = st.b = null; st.routes = []; markers(); render(); status(''); });

  function options() {
    return { bike: $('#bike').value, dark: $('#dark').checked, infra_only: $('#infra').checked,
      avoid: [...document.querySelectorAll('[name=avoid]:checked')].map(x => x.value),
      wind_kmh: +$('#wind').value, wind_from_deg: +$('#wdir').value };
  }

  function plan() {
    if (!st.a || (st.kind === 'ab' && !st.b)) { status(st.kind === 'ab' ? 'Set both A and B first.' : 'Set a start first.'); return; }
    const opts = options(), ctx = makeContext(opts), t0 = performance.now();
    try {
      if (st.kind === 'ab') {
        const rs = eng.router.alternatives([st.a.lat, st.a.lon], [st.b.lat, st.b.lon], { ctx });
        const fastest = Math.min(...rs.map(r => r.timeS));
        st.routes = rs.map(r => ({ r, stats: rate(r, fastest) }));
      } else {
        st.routes = generateLoops(eng.router, [st.a.lat, st.a.lon], +$('#lkm').value, $('#lprof').value, 3, ctx)
          .map(([r, stats]) => ({ r, stats }));
      }
      st.sel = 0;
      status(`${st.routes.length} route${st.routes.length === 1 ? '' : 's'} in ${Math.round(performance.now() - t0)} ms (in your browser).`);
    } catch (e) {
      st.routes = []; status(e.message);
    }
    st.request = { kind: st.kind, a: st.a, b: st.b, km: +$('#lkm').value, profile: $('#lprof').value, opts };
    render();
  }

  function render() {
    const items = st.routes.map(({ r, stats }) => ({ profile_label: r.kind === 'loop' ? `${M.profiles[r.profile].label} loop` : (M.profiles[r.profile]?.label || r.profile),
      also_best_for: (r.meta.also_matches || []).map(p => M.profiles[p].label), stats }));
    map.setRoutes(st.routes.map(({ r }, i) => ({ coords: r.coords(), color: ROUTE_COLORS[i % ROUTE_COLORS.length], selected: i === st.sel })));
    const host = $('#results');
    if (!items.length) { host.innerHTML = ''; $('#pycheck').innerHTML = ''; return; }
    const sel = st.routes[st.sel];
    host.innerHTML = `<h2>${items.length} rated option${items.length === 1 ? '' : 's'}</h2>
      ${sel.stats.context.length ? `<p class="small mute">Conditions: ${esc(sel.stats.context.join(' · '))}</p>` : ''}
      <div class="grid wide">${items.map((it, i) => routeCard(it, i, M.lts_colors, { selected: i === st.sel })).join('')}</div>
      <div class="two"><div><h3>Directions: ${esc(items[st.sel].profile_label)}</h3>${cueList(cueSheet(sel.r), M.lts_colors)}</div>
      <div><h3>Elevation</h3>${elevationSvg(elevKm(sel.r))}<p class="small mute">Max sustained grade ${sel.stats.max_grade_pct}% · ${sel.stats.ascent_m} m up, ${sel.stats.descent_m} m down.</p></div></div>`;
    bindCards(host, i => { st.sel = i; render(); });
    $('#pycheck').innerHTML = isStatic() ? needsServer('"Check with Python"')
      : '<button type="button" class="alt" id="pybtn">Check with Python</button><div id="pyout" class="small"></div>';
    if (!isStatic()) $('#pybtn').addEventListener('click', checkPython);
  }

  async function checkPython() {
    const q = st.request, out = $('#pyout');
    out.textContent = 'Asking the Python router…';
    try {
      const body = { ...q.opts, start: [q.a.lat, q.a.lon] };
      const py = q.kind === 'ab' ? await api('/route', { body: { ...body, end: [q.b.lat, q.b.lon] } })
        : await api('/loop', { body: { ...body, km: q.km, profile: q.profile, count: 3 } });
      out.innerHTML = compareRoutes(st.routes, py);
    } catch (e) { out.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  }
});
