"""Screenshot scenarios for planning features: ride settings & conditions, via points,
comparison, data layers, press-and-hold menu (hazards, feedback, places), favourites,
share links, the More tab and the extra print layouts."""

import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from cycleroutes.devtools.scenarios import Points, _open, frame
from cycleroutes.devtools.session import ShotSession


def _route(sess: ShotSession, pts: Points) -> None:
    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)
    sess.wait_for_results()


def settings_and_via(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    sess.page.click("#settings summary")
    sess.page.select_option("#bike-type", "road")
    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=13, minute=0).strftime("%Y-%m-%dT%H:%M")
    sess.page.fill("#depart", tomorrow)
    sess.page.dispatch_event("#depart", "change")
    sess.page.wait_for_function("() => document.querySelector('#conditions').textContent.includes('Sunrise')")
    cond = sess.page.inner_text("#conditions")
    sess.check("Conditions show daylight and weather", "Sunrise" in cond and "Feels like" in cond, cond[:160])
    sess.check("Summary names the bike", "Road bike" in sess.page.inner_text("#settings-summary"))
    sess.shot("settings", "Ride settings: bike type and departure time; live weather, daylight and closures.",
              element="#panel")

    _route(sess, pts)
    status = sess.page.inner_text("#status")
    sess.check("Routes planned for the chosen conditions", "planned for" in status and "Road bike" in status, status)
    sess.page.click("#via-add")
    mid = ((pts.a[0] + pts.b[0]) / 2, (pts.a[1] + pts.b[1]) / 2 + 0.012)
    sess.click_map(*mid)
    sess.wait_for_results()
    sess.page.wait_for_timeout(800)
    sess.expect_count(".via-row", 1, "Via point listed")
    sess.check("Via pin on map", sess.page.locator(".via-pin").count() == 1)
    sess.shot("via_point", "Adding a stop on the way: numbered, draggable via point reshapes the route.")

    sess.page.click("#compare-go")
    sess.page.wait_for_selector(".compare table")
    rows = sess.page.locator(".compare tbody tr").count()
    sess.check("Comparison table with open-data rows", rows >= 10, f"{rows} rows")
    sess.shot("compare", "Compare all options side by side: crashes, busy crossings, traffic, noise, shade…",
              element="#panel")


def layers_and_menu(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    sess.page.click("[data-tab=more]")
    for name in ("crashes", "workzones", "bikeshare", "counters"):
        sess.page.check(f"[data-layer={name}]")
    sess.page.wait_for_timeout(3500)
    frame(sess, [pts.a, pts.b])
    sess.check("Crash markers drawn", sess.page.locator("path.leaflet-interactive").count() > 20)
    sess.check("Counter and bike-share markers drawn", sess.page.locator(".poi-count").count() >= 1 and
               sess.page.locator(".poi").count() >= 5)
    sess.shot("data_layers", "Open-data layers: bike crashes (red), road works (orange/red), bike share, counters.")
    for name in ("crashes", "workzones", "bikeshare", "counters"):
        sess.page.uncheck(f"[data-layer={name}]")

    score = sess.page.inner_text("#network-score")
    sess.check("Network score shown", "/100" in score, score[:80])
    sess.check("Data sources listed", "3DEP" in sess.page.inner_text("#sources"))
    sess.shot("more_tab", "More: map layers, GPS source, low-stress network score, areas and data sources.",
              element="#panel", tall=True)

    sess.page.click("[data-tab=ab]")
    x, y = sess.latlng_point(*pts.a)
    sess.page.mouse.click(x, y, button="right")
    sess.page.wait_for_selector(".ctx-menu")
    sess.shot("context_menu", "Press-and-hold menu: set points, rate the street, report a hazard, save a place.")
    sess.page.click(".ctx-menu details:nth-of-type(1) summary")
    sess.page.select_option(".ctx-menu [data-f=kind]", "pothole")
    sess.page.fill(".ctx-menu [data-f=note]", "Screenshot test pothole")
    sess.page.click(".ctx-menu [data-a=hazard]")
    sess.page.wait_for_timeout(800)
    sess.check("Hazard report accepted", "Thanks" in sess.page.inner_text("#status"))
    sess.page.mouse.click(x + 40, y + 40, button="right")
    sess.page.wait_for_selector(".ctx-menu")
    sess.page.click(".ctx-menu details:nth-of-type(2) summary")
    sess.page.fill(".ctx-menu [data-f=place]", "Home")
    sess.page.click(".ctx-menu [data-a=place]")
    sess.page.wait_for_selector(".chip")
    sess.check("Saved place appears as a chip", "Home" in sess.page.inner_text("#place-chips"))
    sess.page.click("[data-tab=more]")
    sess.page.check("[data-layer=hazards]")
    sess.page.wait_for_timeout(1200)
    sess.page.click("[data-tab=ab]")
    frame(sess, [pts.a, pts.b])
    sess.check("Reported hazard shown on map", sess.page.locator(".poi-hazard").count() >= 1)
    sess.shot("hazard_and_place", "The reported pothole (⚠) now steers routes away; 'Home' is a one-tap chip.")
    sess.page.uncheck("[data-layer=hazards]") if sess.page.locator("[data-layer=hazards]").is_visible() else None


def favourites_and_links(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    _route(sess, pts)
    sess.page.locator(".card.selected [data-act=save]").click()
    sess.page.wait_for_timeout(600)
    sess.check("Route saved", "Saved" in sess.page.inner_text("#status"))
    sess.page.locator(".card.selected [data-act=link]").click()
    sess.page.wait_for_timeout(600)
    status = sess.page.inner_text("#status")
    link = status if status.startswith("http") else None
    if link is None:   # clipboard worked: rebuild the link the same way the page does
        link = sess.page.evaluate("""() => { const r = window.cycleRoutes.state.routes[0].request;
            const q = new URLSearchParams(); const pt = p => p.map(n => Number(n).toFixed(5)).join(',');
            q.set('start', pt(r.start)); q.set('end', pt(r.end)); if (r.profile) q.set('profile', r.profile);
            return location.origin + '/?' + q; }""")
    sess.check("Share link produced", "start=" in link, link[:100])
    sess.page.click("[data-tab=rides]")
    sess.page.click("#favs-go")
    sess.page.wait_for_selector("[data-plan]")
    sess.shot("favourites", "Rides › Saved routes: plan any saved route again with one tap.", element="#panel")

    other = sess.page.context.new_page()
    other.goto(link)
    other.wait_for_selector(".card", timeout=60000)
    other.wait_for_timeout(2000)
    sess.check("Opening a share link re-plans the route", other.locator(".card").count() >= 1)
    other.screenshot(path=sess.out_dir / "_link.png")
    other.close()
    sess.attach_image("share_link", "A shared link opened in a fresh browser tab re-plans the same route.",
                      sess.out_dir / "_link.png")


def print_layouts(sess: ShotSession, url: str, pts: Points) -> None:
    import pymupdf
    _open(sess, url)
    _route(sess, pts)
    rid = sess.page.evaluate("window.cycleRoutes.state.selected")
    for layout, label in (("strip", "Strip maps: close-up map every 3 km"), ("card", "A6 handlebar cue card with QR code"),
                          ("standard&scale=10000", "Overview map at a fixed 1:10,000 scale")):
        res = sess.page.request.get(f"{url}api/export/{rid}.pdf?layout={layout}", timeout=180000)
        ok = res.status == 200 and res.body()[:4] == b"%PDF"
        sess.check(f"PDF layout '{layout}' renders", ok, f"HTTP {res.status}")
        if ok:
            doc = pymupdf.open(stream=res.body(), filetype="pdf")
            page = 1 if layout == "strip" and doc.page_count > 1 else 0
            tmp = Path(tempfile.mkstemp(suffix=".png")[1])
            doc[page].get_pixmap(dpi=70).save(tmp)
            sess.attach_image(f"print_{layout.split('&')[0]}{'_scale' if 'scale' in layout else ''}", label, tmp)


def road_options_and_trails(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    sess.page.click("#settings summary")
    sess.page.check("[data-avoid=major]")
    sess.page.check("[data-avoid=busy]")
    sess.page.check("#infra-only")
    sess.page.wait_for_timeout(600)
    summary = sess.page.inner_text("#settings-summary")
    sess.check("Summary shows road options", "bike lanes only" in summary and "avoiding 2" in summary, summary)
    sess.shot("road_options", "Ride settings: avoid major and busy roads; bike lanes, cycle paths & trails only.",
              element="#panel")
    _route(sess, pts)
    status = sess.page.inner_text("#status")
    sess.check("Routes planned with the road options", "avoiding" in status and "bike lanes" in status, status)
    infra = [float(m.group(1)) for t in sess.page.locator(".card.selected .facts").all_inner_texts()
             for m in [re.search(r"([\d.]+)% bike infrastructure", t)] if m]
    sess.check("Selected route mostly on bike infrastructure", bool(infra) and infra[0] >= 50, str(infra))
    sess.shot("bike_lanes_only", "Bike lanes & trails only: routes stick to dedicated bike space where they can.")
    for k in ("major", "busy"):
        sess.page.uncheck(f"[data-avoid={k}]")
    sess.page.uncheck("#infra-only")

    sess.page.click("[data-tab=more]")
    sess.page.check("[data-layer=trails]")
    sess.page.wait_for_timeout(2500)
    frame(sess, [pts.loop, pts.b])
    n = sess.page.evaluate("document.querySelectorAll('.leaflet-overlay-pane path').length")
    sess.check("Trail lines drawn", n > 50, f"{n} paths")
    sess.shot("trails_layer", "Cycle trails layer: paved greenways (green), unpaved (brown dashes), MTB grade 2+ (red).")
    sess.page.uncheck("[data-layer=trails]")

    sess.page.click("[data-tab=loop]")
    frame(sess, [pts.loop])
    sess.click_map(*pts.loop)
    sess.page.select_option("#loop-profile", "trails")
    sess.page.fill("#loop-km", "15")
    sess.page.dispatch_event("#loop-km", "input")
    sess.page.click("#loop-go")
    sess.wait_for_results()
    facts = " ".join(sess.page.locator(".card.selected .facts").all_inner_texts())
    sess.check("Trail loop reports its share of trails", "% on trails" in facts, facts[:160])
    sess.shot("trail_loop", "15 km 'Trails & greenways' loop, maximising car-free trails.")


def stale_results_are_dropped(sess: ShotSession, url: str, pts: Points) -> None:
    """Regression: a slow planning response must not draw routes after a tab switch."""
    _open(sess, url)
    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)          # starts planning...
    sess.page.click("[data-tab=more]")   # ...then leave before it returns
    sess.page.wait_for_timeout(6000)
    drawn = sess.page.evaluate("document.querySelectorAll('.leaflet-overlay-pane path.leaflet-interactive').length")
    sess.check("No routes drawn after leaving the tab", drawn == 0, f"{drawn} route paths")
    sess.check("No route cards on the More tab", sess.page.locator(".card").count() == 0)
    sess.shot("stale_results", "Switching tab while routes are being planned: the late answer is ignored.")
