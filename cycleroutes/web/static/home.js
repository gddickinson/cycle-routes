// Home page: hero with the demo network, real counts from /api/info, cards to the pages, how the site works.
import { route, api, app, esc, isStatic, onLeave, $ } from './core.js';
import { engine } from './engine.js';
import { MapView } from './map_view.js';

route('home', async () => {
  const [info, eng] = await Promise.all([api('/info'), engine()]);
  const s = info.summary, M = eng.model;
  const calm = (s.lts_km[1] + s.lts_km[2]) / Math.max(s.network_km, 0.1) * 100;
  app().innerHTML = `
  <section class="hero split">
    <div>
      <p class="kicker">OpenStreetMap · scored street by street</p>
      <h1 class="glow">Cycle Routes</h1>
      <p class="lead">Low-stress, fun bike rides and walks, generated automatically from open data. Every street is
      scored for traffic stress, safety, quiet, scenery, surface and hills; routes are generated for each riding style
      and rated 0-10 on every factor.</p>
      <a class="btn" href="#/explore">Plan a ride</a><a class="btn alt" href="#/examples">Example routes</a>
    </div>
    <figure class="hero-map"><div id="mini"></div>
      <figcaption class="small mute">The demo area, ${esc(info.area.title)}: ${s.network_km} km of rideable streets and paths,
      coloured by traffic stress (green = calm, red = busy).</figcaption></figure>
  </section>
  <div class="tiles">
    <div class="tile"><b>${s.network_km}</b><span>km of streets and paths in the demo area</span></div>
    <div class="tile"><b>${Math.round(calm)}%</b><span>of it low stress (LTS 1-2)</span></div>
    <div class="tile"><b>${info.profiles}</b><span>riding styles (and ${info.walk_profiles} walking trip types in the full app)</span></div>
    <div class="tile"><b>${info.bike_types}</b><span>bike types, ${info.avoid_types} kinds of road to avoid</span></div>
    <div class="tile"><b>${s.risky_crossings}</b><span>unsignalised busy-road crossings flagged</span></div>
  </div>
  <div class="grid">
    <a class="card" href="#/explore"><b>Plan a ride</b><small>A→B or loops, in your browser</small><span>Tap two points: one route per riding style, rated on safety, fun, quiet, hills, speed and surface, with directions.</span></a>
    <a class="card" href="#/examples"><b>Example routes</b><small>computed by the Python router</small><span>Journeys between parks and suggested loops, re-rated in your browser to check the port.</span></a>
    <a class="card" href="#/scoring"><b>Street scores</b><small>from OSM tags to LTS</small><span>Type a street's tags and see its traffic stress and scores; the weights of every riding style.</span></a>
    <a class="card" href="#/area"><b>Your area</b><small>the full local app</small><span>Build any city from OpenStreetMap and open data, then plan, ride, print and export.</span></a>
  </div>
  <h2>How this site works</h2>
  <div class="flow">
    <div>The demo area's streets were downloaded from OpenStreetMap (Overpass) with <code>cycleroutes build</code> and stored
      with their raw tags, elevation and park/water share (${esc(info.area.built || 'date unknown')}).</div>
    <div>Scoring (<code>lts.py</code>, <code>edge_scores.py</code>), the router (bidirectional Dijkstra, as in networkx), loops,
      ratings and directions are ported to JavaScript; node tests require identical routes and ratings to the Python.</div>
    <div>${isStatic() ? 'Building a new area needs OpenStreetMap downloads, so it runs only in the local app (see Your area).'
      : 'In this local app every planner result can be checked against the Python router, and any area you have built opens in the full planner.'}</div>
  </div>
  <p class="callout small" role="note"><b>Safety:</b> ${esc(info.safety_notice)}</p>`;
  const map = new MapView($('#mini'), eng, { height: 320 });
  onLeave(() => map.destroy());
  void M;
});
