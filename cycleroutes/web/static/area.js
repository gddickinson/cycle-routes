// Your area: route generation for a new place needs OpenStreetMap downloads, so it lives in the full local app.
// In the local app this page lists the areas already built on this machine.
import { route, app, api, esc, isStatic, needsServer } from './core.js';

const BUILD = `pip install -e '.[dev]'
cycleroutes build --name bath --lat 51.381 --lon -2.359 --radius 5000   # streets + open data for the area
cycleroutes catalog --region bath                                         # optional: suggested rides
cycleroutes serve --region bath                                           # full planner on http://127.0.0.1:8000`;

route('area', async () => {
  let built = '';
  if (isStatic()) {
    built = needsServer('Listing and opening the areas built on your machine');
  } else {
    const r = await api('/areas', { fresh: true });
    built = r.areas.length
      ? `<div class="scroll"><table><thead><tr><th>Area</th><th>Street data</th><th>Built</th><th>Open it</th></tr></thead><tbody>${r.areas.map(a => `<tr>
          <td><b>${esc(a.name)}</b></td><td class="small">${esc(a.network)}</td>
          <td class="small">${a.built ? new Date(a.built * 1000).toISOString().slice(0, 10) : '?'}</td>
          <td><code>cycleroutes serve --region ${esc(a.name)}</code></td></tr>`).join('')}</tbody></table></div>`
      : `<p class="mute">No areas built yet in <code>${esc(r.data_dir)}</code>.</p>`;
  }
  app().innerHTML = `
  <p class="kicker">Your own city</p>
  <h1>Routes for your area</h1>
  <p class="lead">The full app downloads the streets for any area covered by OpenStreetMap (from a local extract or the
  Overpass API), adds elevation and whatever extra open data covers it, scores every street and then generates rated
  A→B routes, loops of any length, trips with stops, suggested rides, walks and sightseeing tours.</p>
  <h2>Areas built on this machine</h2>
  ${built}
  <h2>Build an area and open the planner</h2>
  <pre>${esc(BUILD)}</pre>
  <p>Datasets that don't cover an area are skipped and elevation falls back to Copernicus. The full planner adds live
  weather, road-work closures, hazard reports, voice navigation, ride recording, printable maps and GPX export (see the
  README). Downloads are cached in <code>data_cache/</code>; please keep within the public servers' usage policies
  (README, "Usage policies").</p>
  <div class="callout">The public Overpass, Nominatim and tile servers are run by volunteers for light use, which is
  why this static site plans routes only on a pre-downloaded demo area and never downloads map data itself.</div>`;
});
