// About page: what the project is, safety, how to run the full app and this site, data credits (README).
import { route, app, api, esc, list } from './core.js';

route('about', async () => {
  const info = await api('/info');
  const a = info.area;
  app().innerHTML = `
  <p class="kicker">About</p>
  <h1>Cycle Routes</h1>
  <p class="lead">Most route planners find you the shortest way. Cycle Routes looks for the way you'd actually want to
  ride: it downloads street data and other open datasets for an area, scores every street for traffic stress, safety,
  traffic volume, scenery, shade, hills, surface and speed, and generates A→B journeys per riding style, loops of any
  length, suggested rides and trips with stops. It was built and tested on Austin, Texas; the core works in any city
  covered by OpenStreetMap.</p>

  <h2>Safety</h2>
  <div class="callout"><p><b>Routes are generated automatically and have not been checked by anyone. Do not rely on this
  site or the app for safe navigation.</b> ${esc(info.safety_notice)}</p>
  <p>OpenStreetMap and the other datasets have gaps and errors; ratings are estimates, not guarantees. Check a route
  before you set off, obey traffic signs and laws, and don't take any part that looks unsafe.</p></div>

  <h2>This site</h2>
  <p>A showcase of the routing engine on one demo area, <b>${esc(a.title)}</b> (${Math.round(a.radius_m)} m around
  ${a.lat.toFixed(4)}, ${a.lon.toFixed(4)}), built ${esc(a.built || '')} with <code>cycleroutes build</code>. Sources used for it:</p>
  <ul class="small">${list(Object.entries(a.sources), ([k, v]) => `<li><b>${esc(k)}</b>: ${esc(v)}</li>`)}</ul>
  <p>The browser runs a JavaScript port of the scoring, router, loops, ratings and directions, tested in node against
  the Python on the same graph. The example routes are computed by the Python itself. The map draws the OpenStreetMap
  streets directly (no map tiles are loaded).</p>

  <h2>Run the full app</h2>
  <pre>git clone https://github.com/gddickinson/cycle-routes.git && cd cycle-routes
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/cycleroutes build          # Austin, 10 km radius: streets + all open data
.venv/bin/cycleroutes serve          # → http://127.0.0.1:8000</pre>
  <h2>Run this site locally</h2>
  <pre>pip install -r requirements-web.txt
python run_web.py                    # → http://127.0.0.1:8184</pre>
  <p>Build the static site with <code>python scripts/build_static.py</code>; tests: <code>python -m pytest -q tests/test_web.py</code>
  (includes the node engine tests). The demo area is refreshed with <code>scripts/make_demo_area.py</code> after a local build.</p>

  <h2>Credits &amp; licences</h2>
  <ul>
    <li>Map data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors, available under the Open Database Licence (ODbL). The demo area's street graph is derived from it and stays under the ODbL.</li>
    <li>Elevation: Copernicus GLO-30 (© ESA/DLR) and USGS 3DEP (public domain) in the full app.</li>
    <li>The full app also uses Overture Maps places, Meta/WRI canopy, US DOT noise, TxDOT traffic counts, City of Austin open data and Open-Meteo weather where they cover an area (see the README).</li>
    <li>Parts of the GPS and tracking code come from the author's gps-tracker and pyNav projects.</li>
  </ul>
  <p>Code: MIT licence, no warranty. Built with AI assistance from <a href="https://claude.com/" target="_blank" rel="noopener">Claude (Anthropic)</a>.
  Source: <a href="https://github.com/gddickinson/cycle-routes" target="_blank" rel="noopener">github.com/gddickinson/cycle-routes</a>.</p>`;
});
