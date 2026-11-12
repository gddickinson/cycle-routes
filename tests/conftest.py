"""Test set-up. The full suite needs the full install (pip install -e '.[dev]'); its fixtures live in full_fixtures.py.

With only requirements-web.txt installed (as in the GitHub Pages workflow) just tests/test_web.py is collected, since
the web app and the demo area need no GIS stack.
"""
import importlib.util
from pathlib import Path

if importlib.util.find_spec("geopandas") is None or importlib.util.find_spec("osmnx") is None:
    collect_ignore = [p.name for p in Path(__file__).parent.glob("test_*.py") if p.name != "test_web.py"]
else:
    from full_fixtures import *  # noqa: F401,F403  (fixtures region/client and grid helpers)
    from full_fixtures import LAT0, LON0, N, STEP, node_latlon  # noqa: F401
