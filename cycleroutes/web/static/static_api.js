// Static-site data layer: answers api() GETs from the JSON files exported by scripts/build_static.py
// (api/info.json, api/model.json, api/demo.json, api/examples.json). The POST endpoints (/route, /loop, /score) and
// /areas run Python on the local machine, so they are refused here; pages show a "needs the local app" note instead.
const files = new Map();
function file(rel) {
  if (!files.has(rel)) {
    files.set(rel, fetch('api/' + rel + '.json').then(r => { if (!r.ok) throw new Error(`${r.status} ${rel}`); return r.json(); }));
  }
  return files.get(rel);
}

export async function staticApi(path, body) {
  const clean = path.split('?')[0].replace(/^\/+/, '');
  if (body || ['route', 'loop', 'score', 'areas'].includes(clean)) {
    throw new Error('This needs the local app with its Python server (python run_web.py).');
  }
  return file(clean);
}
