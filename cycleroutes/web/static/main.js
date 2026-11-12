// Entry point: lazy page modules, footer mode text, router.
import { start, lazy, route, app, isStatic, $ } from './core.js';

const PAGES = { 'home.js': ['home'], 'explore.js': ['explore'], 'examples.js': ['examples'], 'scoring.js': ['scoring'],
  'area.js': ['area'], 'about.js': ['about'] };
lazy(Object.fromEntries(Object.entries(PAGES).flatMap(([file, names]) => names.map(n => [n, () => import('./' + file)]))));

route('notfound', () => { app().innerHTML = '<h1>Not found</h1><p><a href="#/">Back to the start</a></p>'; });

$('#mode').textContent = isStatic()
  ? 'static site: routes are computed in your browser'
  : 'local app: browser engine + Python router at /api';
start();
