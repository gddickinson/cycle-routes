# Cycle Routes

@INTERFACE.md

- Python venv: `.venv/bin/python` (Python 3.14). Install: `.venv/bin/pip install -e '.[dev]'`.
- Tests are offline: `.venv/bin/python -m pytest -q`.
- UI check: `.venv/bin/cycleroutes screenshots --out screenshots` then LOOK at the PNGs (checks passing
  is not enough - several layout bugs were only visible in the images). Report: screenshots/report.html.
- Downloaded/derived data lives in `data_cache/` (git-ignored); rebuild with `cycleroutes build`.
- All tunable defaults belong in `cycleroutes/config.py` — no magic numbers elsewhere.
- Keep every file under 500 lines; update INTERFACE.md and SESSION_LOG.md when structure changes.
