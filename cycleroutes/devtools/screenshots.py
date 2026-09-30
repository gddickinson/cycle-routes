"""Drive the web app headlessly and produce screenshots + checks + an HTML report.

    cycleroutes screenshots                  # starts its own server on a free port
    cycleroutes screenshots --url http://127.0.0.1:8765/ --out shots/

Needs Playwright (`pip install -e '.[dev]'`) and Google Chrome (or run
`playwright install chromium`).
"""

import logging
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from cycleroutes import config
from cycleroutes.devtools import (scenarios, scenarios_extend, scenarios_offline, scenarios_plan, scenarios_ride,
                                  scenarios_trip, scenarios_walk)
from cycleroutes.devtools.report import write_report
from cycleroutes.devtools.session import Shot, ShotSession, write_manifest

logger = logging.getLogger(__name__)

DESKTOP = {"viewport": {"width": 1400, "height": 900}}
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
         "is_mobile": True, "has_touch": True}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def app_server(url: str | None, region: str, scratch: Path | None = None):
    """Yield a base URL, starting a temporary server when none is given."""
    if url:
        yield url if url.endswith("/") else url + "/"
        return
    port = _free_port()
    env = dict(os.environ, CYCLEROUTES_REGION=region)
    if scratch:  # keep test rides out of the real ride history; start clean each run
        (scratch / "test-rides.sqlite").unlink(missing_ok=True)
        env["CYCLEROUTES_RIDES_DB"] = str(scratch / "test-rides.sqlite")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "cycleroutes.api.app:app",
                             "--port", str(port), "--log-level", "warning"],
                            env=env, cwd=config.PROJECT_ROOT)
    base = f"http://127.0.0.1:{port}/"
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if requests.get(base + "api/region", timeout=5).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            raise RuntimeError("Web app did not start")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _launch(p):
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:  # no Chrome installed: fall back to Playwright's Chromium
        return p.chromium.launch(headless=True)


def _run_group(browser, name: str, context_opts: dict, out_dir: Path, shots: list[Shot], fn) -> None:
    ctx = browser.new_context(**context_opts)
    # Automated runs must be silent: headless Chrome still speaks through the OS voice.
    ctx.add_init_script("""(() => { if (window.speechSynthesis) {
        window.speechSynthesis.speak = (u) => { window.__spoken = (window.__spoken || []).concat(u.text); };
      } })();""")
    page = ctx.new_page()
    page.set_default_timeout(30000)
    sess = ShotSession(page, out_dir, name, shots)
    try:
        fn(sess)
    except Exception as exc:  # keep going: record the failure with a screenshot
        logger.exception("Scenario %s crashed", name)
        sess.check(f"Scenario '{name}' ran to completion", False, f"{type(exc).__name__}: {exc}")
        sess.shot("crash", f"Scenario stopped here: {type(exc).__name__}")
    finally:
        ctx.close()


def run(out_dir: Path, url: str | None = None, region: str = config.DEFAULT_REGION["name"]) -> list[Shot]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    shots: list[Shot] = []
    with app_server(url, region, out_dir) as base:
        info = requests.get(base + "api/region", timeout=30).json()
        pts = scenarios.Points(info["bbox"])
        with sync_playwright() as p:
            browser = _launch(p)
            _run_group(browser, "desktop", DESKTOP, out_dir, shots, lambda s: (
                scenarios.desktop_core(s, base, pts), scenarios.desktop_search(s),
                scenarios.desktop_loops_and_suggested(s, pts), scenarios.exports(s, base),
                scenarios_ride.amenities(s, pts)))
            for name, fn in (("settings", scenarios_plan.settings_and_via), ("layers", scenarios_plan.layers_and_menu),
                             ("saving", scenarios_plan.favourites_and_links), ("print", scenarios_plan.print_layouts),
                             ("roads", scenarios_plan.road_options_and_trails),
                             ("race", scenarios_plan.stale_results_are_dropped)):
                _run_group(browser, name, DESKTOP, out_dir, shots, lambda s, fn=fn: fn(s, base, pts))
            _run_group(browser, "walk", DESKTOP, out_dir, shots, lambda s: scenarios_walk.walking(s, base, pts))
            _run_group(browser, "trip", DESKTOP, out_dir, shots, lambda s: scenarios_trip.trip_builder(s, base, pts))
            _run_group(browser, "extend", DESKTOP, out_dir, shots,
                       lambda s: scenarios_extend.extend_suggested(s, base, pts))
            _run_group(browser, "offline", DESKTOP, out_dir, shots,
                       lambda s: scenarios_offline.offline(s, base, pts))
            _run_group(browser, "phone", PHONE, out_dir, shots,
                       lambda s: scenarios.phone(s, base, pts))
            _run_group(browser, "ride", PHONE | {"permissions": ["geolocation"],
                       "geolocation": {"latitude": pts.a[0], "longitude": pts.a[1]}}, out_dir, shots,
                       lambda s: scenarios_ride.ride(s, base, pts))
            _run_group(browser, "dark", DESKTOP | {"color_scheme": "dark"}, out_dir, shots,
                       lambda s: scenarios.dark(s, base, pts))
            browser.close()
    meta = {"started": datetime.now().strftime("%Y-%m-%d %H:%M"), "region": info["name"], "url": base}
    write_manifest(out_dir, shots, meta)
    write_report(out_dir, shots, meta)
    return shots


def print_summary(shots: list[Shot], out_dir: Path) -> bool:
    ok = True
    for s in shots:
        mark = "ok " if s.ok else "FAIL"
        print(f"[{mark}] {s.file}")
        for c in s.checks:
            if not c["ok"]:
                ok = False
                print(f"        ✗ {c['label']}  {c['detail']}")
        for prob in s.problems:
            ok = False
            print(f"        ✗ {prob}")
    n_checks = sum(len(s.checks) for s in shots)
    print(f"\n{len(shots)} screenshots, {n_checks} checks -> {out_dir / 'report.html'}")
    return ok
