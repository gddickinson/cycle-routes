"""Screenshot session: a headless browser page that records numbered screenshots
plus automatic checks (JS errors, failed API calls, expectations) for each step.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from playwright.sync_api import Page

# API responses that scenarios deliberately provoke are not failures.
EXPECTED_HTTP_ERRORS = re.compile(r"/api/export/nope|start=31\.0")


@dataclass
class Shot:
    index: int
    group: str
    name: str
    caption: str
    file: str
    checks: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and all(c["ok"] for c in self.checks)


class ShotSession:
    """Wraps one Playwright page; each `shot()` saves a PNG and the step's checks."""

    def __init__(self, page: Page, out_dir: Path, group: str, shots: list[Shot]):
        self.page, self.out_dir, self.group, self.shots = page, out_dir, group, shots
        self._problems: list[str] = []
        self._checks: list[dict] = []
        page.on("pageerror", lambda e: self._problems.append(f"JavaScript error: {e}"))
        page.on("console", self._on_console)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)

    # --- automatic problem capture ---------------------------------------------
    def _on_console(self, msg) -> None:
        if msg.type == "error" and "Failed to load resource" not in msg.text:
            self._problems.append(f"Console error: {msg.text}")

    def _on_response(self, resp) -> None:
        if "/api/" in resp.url and resp.status >= 400 and not EXPECTED_HTTP_ERRORS.search(resp.url):
            self._problems.append(f"HTTP {resp.status} from {resp.url.split('/api/')[1][:90]}")
        if "/static/" in resp.url and resp.status >= 400:
            self._problems.append(f"Missing file: {resp.url}")

    def _on_request_failed(self, req) -> None:
        if "127.0.0.1" in req.url and "/api/" in req.url:
            self._problems.append(f"Request failed: {req.url} ({req.failure})")

    # --- explicit expectations -------------------------------------------------
    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self._checks.append({"label": label, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def expect_count(self, selector: str, minimum: int, label: str) -> int:
        n = self.page.locator(selector).count()
        self.check(label, n >= minimum, f"{n} found (need ≥ {minimum})")
        return n

    def expect_status(self, pattern: str, label: str, error: bool = False) -> str:
        text = self.page.inner_text("#status")
        is_error = "error" in (self.page.get_attribute("#status", "class") or "")
        self.check(label, re.search(pattern, text) is not None and is_error == error, repr(text))
        return text

    def expect_visible_in_viewport(self, selector: str, label: str) -> None:
        box = self.page.locator(selector).first.bounding_box()
        vw = self.page.viewport_size
        ok = bool(box) and box["x"] >= -1 and box["y"] >= -1 and \
            box["x"] + box["width"] <= vw["width"] + 1 and box["y"] + box["height"] <= vw["height"] + 1
        self.check(label, ok, f"box={box}")

    def expect_no_horizontal_scroll(self) -> None:
        sw = self.page.evaluate("document.documentElement.scrollWidth")
        self.check("No horizontal page scroll", sw <= self.page.viewport_size["width"], f"scrollWidth={sw}")

    # --- actions ------------------------------------------------------------------
    def wait_for_tiles(self, timeout_ms: int = 8000) -> None:
        """Wait until visible map tiles have loaded (best effort)."""
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            pending = self.page.evaluate(
                "document.querySelectorAll('.leaflet-tile-container img:not(.leaflet-tile-loaded)').length")
            if pending == 0:
                break
            self.page.wait_for_timeout(200)
        self.page.wait_for_timeout(400)

    def wait_for_results(self, timeout_ms: int = 60000) -> None:
        self.page.wait_for_function(
            "() => { const s = document.querySelector('#status'); return document.querySelector('.card') "
            "|| (s && s.classList.contains('error')); }", timeout=timeout_ms)

    def latlng_point(self, lat: float, lng: float) -> tuple[float, float]:
        x, y = self.page.evaluate(
            "ll => { const p = window.cycleRoutes.map.latLngToContainerPoint(ll); return [p.x, p.y]; }",
            [lat, lng])
        return x, y

    def click_map(self, lat: float, lng: float) -> None:
        x, y = self.latlng_point(lat, lng)
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(200)

    def view(self, lat: float, lng: float, zoom: int) -> None:
        self.page.evaluate("a => { window.cycleRoutes.map.setView([a[0], a[1]], a[2], {animate: false}); }",
                           [lat, lng, zoom])
        self.wait_for_tiles()

    # --- recording ----------------------------------------------------------------
    def shot(self, name: str, caption: str, full_page: bool = False, element: str | None = None,
             tall: bool = False) -> Shot:
        """Save a screenshot. tall=True temporarily stretches the window (and lifts the
        results list's height limit) so a long element is captured whole."""
        self.wait_for_tiles()
        size = self.page.viewport_size
        if tall:
            self.page.set_viewport_size({"width": size["width"], "height": 2600})
            self.page.add_style_tag(content=".results{flex:none!important;overflow:visible!important}"
                                            ".cues{max-height:none!important}")
            self.page.wait_for_timeout(300)
        index = len(self.shots) + 1
        filename = f"{index:02d}_{self.group}_{name}.png"
        target = self.out_dir / filename
        if element:
            self.page.locator(element).first.screenshot(path=target)
        else:
            self.page.screenshot(path=target, full_page=full_page)
        if tall:
            self.page.set_viewport_size(size)
            self.page.evaluate("document.head.lastElementChild.remove()")
        s = Shot(index, self.group, name, caption, filename, self._checks, self._problems)
        self.shots.append(s)
        self._checks, self._problems = [], []
        return s

    def attach_image(self, name: str, caption: str, path: Path) -> Shot:
        """Record an image produced outside the browser (e.g. a rendered PDF page)."""
        index = len(self.shots) + 1
        filename = f"{index:02d}_{self.group}_{name}.png"
        path.rename(self.out_dir / filename)
        s = Shot(index, self.group, name, caption, filename, self._checks, self._problems)
        self.shots.append(s)
        self._checks, self._problems = [], []
        return s


def write_manifest(out_dir: Path, shots: list[Shot], meta: dict) -> Path:
    path = out_dir / "manifest.json"
    path.write_text(json.dumps({"meta": meta, "shots": [asdict(s) | {"ok": s.ok} for s in shots]},
                               indent=2))
    return path
