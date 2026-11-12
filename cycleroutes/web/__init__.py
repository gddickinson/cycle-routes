"""Showcase web app and static GitHub Pages site (python run_web.py, port 8184).

app.py        FastAPI app: front end in static/, JSON API under /api, STATIC_ENDPOINTS for the static export
model.py      the scoring/routing numbers (config + modules) as JSON for the browser engine
demo_area.py  the committed demo area (demo/<name>.json): load_demo, graph_from_demo (scored nx graph), summary
examples.py   example A->B alternatives and loops computed by the Python router on the demo area
static/       ES-module front end (no build step) incl. the JS port of scoring, router, loops, rating, directions
demo/         the demo area's compact street graph (OpenStreetMap-derived, ODbL)
"""
