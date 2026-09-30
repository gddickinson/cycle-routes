"""Scripted walkthroughs of the web app. Each scenario records screenshots + checks.

Test points are placed relative to the region's bounding box so the scenarios
work for any built region, not only the Austin demo.
"""

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from cycleroutes.devtools.session import ShotSession


class Points:
    """Representative points inside (and just outside) the region."""

    def __init__(self, bbox: list[float]):
        s, w, n, e = bbox
        self.bbox = bbox
        at = lambda fy, fx: (s + fy * (n - s), w + fx * (e - w))  # noqa: E731
        self.a = at(0.68, 0.52)
        self.b = at(0.38, 0.38)
        self.loop = at(0.45, 0.5)
        self.outside = (s + 0.5 * (n - s), w - 0.15 * (e - w))


def frame(sess: ShotSession, points: list[tuple[float, float]]) -> None:
    """Fit the map to points, keeping them clear of the panel (side panel or bottom sheet)."""
    vw = sess.page.viewport_size
    phone = vw["width"] <= 700
    pad_tl = [30, 30] if phone else [430, 60]
    pad_br = [30, int(vw["height"] * 0.58)] if phone else [60, 60]
    sess.page.evaluate("a => { window.cycleRoutes.map.fitBounds(a[0], {paddingTopLeft: a[1], "
                       "paddingBottomRight: a[2], animate: false, maxZoom: 15}); }",
                       [[list(p) for p in points], pad_tl, pad_br])
    sess.wait_for_tiles()


def _selected_id(sess: ShotSession) -> str | None:
    return sess.page.evaluate("window.cycleRoutes.state.selected")


def _open(sess: ShotSession, url: str) -> None:
    sess.page.goto(url)
    sess.page.wait_for_function("window.cycleRoutes !== undefined", timeout=30000)
    sess.wait_for_tiles()


# --- Desktop --------------------------------------------------------------------
def desktop_core(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    sess.expect_count(".legend i", 4, "Legend shows 4 stress levels")
    sess.expect_count(".tab", 3, "Three tabs present")
    sess.expect_status("Tap the map", "Start-up hint shown")
    sess.check("Map tiles loaded", sess.page.locator(".leaflet-tile-loaded").count() > 4)
    sess.shot("start", "First load: mapped area clear, outside shaded, legend and tabs in the panel.")

    frame(sess, [pts.outside, pts.a])
    sess.click_map(*pts.outside)
    sess.expect_status("outside the mapped area", "Outside click rejected with message", error=True)
    sess.check("No start point set", sess.page.evaluate("window.cycleRoutes.state.start") is None)
    sess.shot("outside_click", "Clicking in the shaded area is refused straight away.")

    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.expect_count(".pin", 1, "Start pin placed")
    sess.check("Start field filled", sess.page.input_value("#start-input") != "")
    sess.shot("start_pin", "First tap places the A pin and fills the From box.")

    sess.click_map(*pts.b)
    sess.wait_for_results()
    n = sess.expect_count(".card", 2, "Several alternative routes returned")
    sess.expect_status(r"\d+ options?", "Status reports number of options")
    sess.check("First option selected", sess.page.locator(".card.selected").count() == 1)
    labels = sess.page.locator(".card-title").all_inner_texts()
    sess.check("Route titles are distinct", len(set(labels)) == len(labels), ", ".join(labels))
    sess.shot("ab_results", f"Second tap routes automatically: {n} rated options, first one highlighted.")

    card = sess.page.locator(".card.selected")
    sess.check("Elevation profile drawn", card.locator("svg.elev").count() == 1)
    sess.check("Directions listed", card.locator(".cues li").count() >= 2)
    sess.check("PDF and GPX links present", card.locator("a[href$='.pdf'], a[href$='.gpx']").count() == 2)
    ratings = [float(t) for t in card.locator(".ratings b").all_inner_texts()]
    sess.check("Ratings within 0-10", all(0 <= r <= 10 for r in ratings), str(ratings))
    sess.shot("ab_card_detail", "Selected card close-up: ratings, stress mix, elevation, exports, directions.",
              element=".card.selected", tall=True)

    before = _selected_id(sess)
    sess.page.locator(".card").nth(min(2, n - 1)).click()
    sess.page.wait_for_timeout(600)
    sess.check("Clicking a card selects it", _selected_id(sess) != before)
    sess.shot("ab_other_option", "Choosing another option redraws it on the map; others stay grey.")

    sess.page.click("details.custom summary")
    sess.page.fill("#w-safety", "5")
    sess.page.fill("#w-hills", "4")
    sess.page.click("#custom-go")
    sess.wait_for_results()
    sess.check("Custom mix gives one route", sess.page.locator(".card").count() == 1)
    sess.check("Custom route titled 'Your mix'", "Your mix" in sess.page.inner_text(".card-title"))
    sess.shot("custom_mix", "Custom mix sliders (safety 5, avoid hills 4) produce a single tailored route.")


def desktop_search(sess: ShotSession) -> None:
    sess.page.fill("#start-input", "")
    sess.page.type("#start-input", "park", delay=40)
    try:
        sess.page.wait_for_selector(".suggestions:not(.hidden)", timeout=12000)
        items = sess.page.locator(".suggestions:not(.hidden) div").count()
        sess.check("Search shows suggestions", items >= 1, f"{items} rows")
    except Exception:  # Nominatim is an external service; record rather than crash
        sess.check("Search shows suggestions", False, "no dropdown within 12 s (Nominatim unreachable?)")
    sess.shot("search", "Typing a place name searches Nominatim, limited to the mapped area.", element="#panel")
    sess.page.keyboard.press("Escape")
    sess.page.click("#status")  # blur to close the dropdown


def desktop_loops_and_suggested(sess: ShotSession, pts: Points) -> None:
    sess.page.click("[data-tab=loop]")
    sess.check("Pins cleared when switching tab", sess.page.locator(".pin").count() == 0)
    frame(sess, [pts.loop])
    sess.click_map(*pts.loop)
    sess.page.fill("#loop-km", "12")
    sess.page.dispatch_event("#loop-km", "input")
    sess.page.select_option("#loop-profile", "scenic")
    sess.page.click("#loop-go")
    sess.wait_for_results()
    n = sess.expect_count(".card", 1, "Loops generated")
    km = [float(re.match(r"([\d.]+) km", t).group(1)) for t in sess.page.locator(".card-sub").all_inner_texts()]
    sess.check("Loop lengths near 12 km (±40%)", all(7.2 <= k <= 16.8 for k in km), str(km))
    sess.shot("loops", f"12 km scenic loop request: {n} ranked loops from the S pin.")

    sess.page.click("[data-tab=suggested]")
    sess.wait_for_results()
    n = sess.expect_count(".card", 1, "Suggested rides listed")
    scores = [float(t) for t in sess.page.locator(".card-score").all_inner_texts()]
    sess.check("Suggested rides sorted best first", scores == sorted(scores, reverse=True))
    sess.shot("suggested", f"{n} pre-generated rides, best rated first; only the selected one is drawn.")

    sess.page.check("#stress-toggle")
    sess.page.wait_for_timeout(2500)
    sess.check("Stress layer drawn", sess.page.evaluate(
        "document.querySelectorAll('.leaflet-overlay-pane canvas').length") >= 1)
    sess.shot("stress_layer", "Traffic-stress layer: every street coloured by Level of Traffic Stress.")
    sess.page.uncheck("#stress-toggle")

    sess.page.hover(".leaflet-control-layers")
    sess.page.locator(".leaflet-control-layers-base label", has_text="OpenStreetMap").click()
    sess.page.wait_for_timeout(500)
    sess.check("OSM basemap active", sess.page.locator("img[src*='tile.openstreetmap.org']").count() > 0)
    sess.page.mouse.move(700, 450)
    sess.shot("osm_basemap", "Basemap switched to standard OpenStreetMap via the layers control.")


def exports(sess: ShotSession, url: str) -> None:
    rid = _selected_id(sess)
    if not sess.check("A route is selected for export", rid is not None):
        return
    gpx = sess.page.request.get(f"{url}api/export/{rid}.gpx")
    ok = gpx.status == 200
    points = 0
    if ok:
        root = ET.fromstring(gpx.body())
        ns = {"g": "http://www.topografix.com/GPX/1/1"}
        points = len(root.findall(".//g:trkpt", ns))
        sess.check("GPX has cue waypoints", len(root.findall("g:wpt", ns)) >= 2)
    sess.check("GPX downloads and parses", ok and points > 10, f"HTTP {gpx.status}, {points} track points")

    pdf = sess.page.request.get(f"{url}api/export/{rid}.pdf", timeout=120000)
    if not sess.check("PDF downloads", pdf.status == 200 and pdf.body()[:4] == b"%PDF",
                      f"HTTP {pdf.status}"):
        return
    import pymupdf
    doc = pymupdf.open(stream=pdf.body(), filetype="pdf")
    sess.check("PDF has map + details pages", doc.page_count >= 2, f"{doc.page_count} pages")
    text = doc[1].get_text()
    sess.check("PDF details list directions", "Directions" in text and "km" in text)
    for i, label in ((0, "map page"), (1, "details page")):
        tmp = Path(tempfile.mkstemp(suffix=".png")[1])
        doc[i].get_pixmap(dpi=80).save(tmp)
        sess.attach_image(f"pdf_p{i + 1}", f"Printable PDF, {label} (rendered from the real export).", tmp)

    bad = sess.page.request.get(f"{url}api/export/nope.gpx")
    sess.check("Unknown route id gives 404", bad.status == 404)
    far = sess.page.request.get(f"{url}api/route?start=31.0,-90&end=31.0,-90.01")
    sess.check("Out-of-area API route gives 422 with message", far.status == 422 and
               "outside the mapped region" in far.text())


# --- Phone & dark mode ----------------------------------------------------------
def phone(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    sess.expect_no_horizontal_scroll()
    sess.expect_visible_in_viewport("#panel", "Bottom sheet fits on screen")
    sess.check("Desktop title hidden on phone", not sess.page.locator(".panel-head h1").is_visible())
    sess.shot("start", "Phone: map on top, controls in a bottom sheet.")

    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)
    sess.wait_for_results()
    sess.expect_count(".card", 2, "Routes returned on phone")
    sess.expect_no_horizontal_scroll()
    sess.shot("ab_results", "Phone A→B: route framed above the sheet, rated options below.")

    sess.page.locator("#results").evaluate("el => el.scrollTop = el.scrollHeight")
    sess.page.wait_for_timeout(300)
    sess.shot("ab_scrolled", "Phone: scrolling the sheet reaches the directions and export buttons.")

    h_before = sess.page.locator("#panel").bounding_box()["height"]
    sess.page.click("#panel-handle")
    sess.page.wait_for_timeout(500)
    h_after = sess.page.locator("#panel").bounding_box()["height"]
    sess.check("Handle collapses the sheet", h_after < h_before, f"{h_before:.0f} → {h_after:.0f} px")
    sess.shot("collapsed", "Phone: tapping the handle collapses the sheet to show more map.")
    sess.page.click("#panel-handle")

    sess.page.click("[data-tab=loop]")
    frame(sess, [pts.loop])
    sess.click_map(*pts.loop)
    sess.page.click("#loop-go")
    sess.wait_for_results()
    sess.expect_count(".card", 1, "Loops on phone")
    sess.shot("loops", "Phone loop generator.")


def dark(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    bg = sess.page.evaluate("getComputedStyle(document.querySelector('.panel')).backgroundColor")
    sess.check("Panel uses dark background", bg not in ("rgb(255, 255, 255)",), bg)
    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)
    sess.wait_for_results()
    sess.expect_count(".card", 2, "Routes in dark mode")
    sess.shot("ab_results", "Dark mode (system setting): panel, cards and charts in dark colours.")
