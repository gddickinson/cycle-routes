"""Screenshot scenarios for GPS features: amenities, simulated ride with navigation,
off-route + reroute, arrival, ride summary and the "My rides" list.

GPS movement is simulated with Playwright's geolocation emulation, i.e. through the
same browser Geolocation API a phone uses.
"""

from cycleroutes.devtools.scenarios import Points, _open, frame
from cycleroutes.devtools.session import ShotSession
from cycleroutes.routing.geo import destination, haversine_m


def amenities(sess: ShotSession, pts: Points) -> None:
    frame(sess, [pts.a, pts.b])
    sess.page.check("#amenity-toggle")
    sess.page.wait_for_timeout(1500)
    n = sess.page.locator(".poi").count()
    sess.check("Amenity markers shown", n >= 5, f"{n} markers in view")
    sess.check("No bike-parking clutter at this zoom", sess.page.locator(".poi-parking").count() == 0)
    # click a marker that is visible and on top at its centre (as a user would)
    xy = sess.page.evaluate("""() => { for (const e of document.querySelectorAll('.poi')) {
        const r = e.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
        if (x > 440 && x < innerWidth - 70 && y > 20 && y < innerHeight - 20
            && e.contains(document.elementFromPoint(x, y))) return [x, y]; } return null; }""")
    if sess.check("A clickable amenity marker is visible", xy is not None):
        sess.page.mouse.click(*xy)
    sess.page.wait_for_timeout(400)
    sess.check("Amenity popup opens", sess.page.locator(".leaflet-popup-content").count() == 1)
    sess.shot("amenities", "Amenities: shops 🔧, repair 🛠, bike share 🚲 from afar; water 💧 / toilets 🚻 "
              "closer in; parking 🅿 only at street zoom.")
    sess.view(*pts.a, 17)
    n_park = sess.page.locator(".poi-parking").count()
    sess.check("Zoomed in: bike parking layer active", n_park >= 1, f"{n_park} racks in view")
    sess.shot("amenities_zoomed", "Zoomed to street level: bike parking racks appear too.")
    sess.page.keyboard.press("Escape")
    sess.page.uncheck("#amenity-toggle")


def _route_coords(sess: ShotSession) -> list[tuple[float, float]]:
    """(lat, lon) along the selected route, as drawn on the map."""
    coords = sess.page.evaluate("""() => {
      const s = window.cycleRoutes.state; const r = s.routes.find(x => x.id === s.selected);
      return r.geojson.features.flatMap(f => f.geometry.coordinates); }""")
    return [(lat, lon) for lon, lat in coords]


def _along(coords, fraction: float) -> tuple[float, float]:
    """Point at a fraction of the route's length."""
    dists = [0.0]
    for (a, b), (c, d) in zip(coords[:-1], coords[1:]):
        dists.append(dists[-1] + float(haversine_m(a, b, c, d)))
    target = dists[-1] * fraction
    i = next(k for k, v in enumerate(dists) if v >= target) if target > 0 else 0
    return coords[i]


def _move(sess: ShotSession, latlon, accuracy: float = 6.0, wait_ms: int = 900) -> None:
    sess.page.context.set_geolocation({"latitude": latlon[0], "longitude": latlon[1], "accuracy": accuracy})
    sess.page.wait_for_timeout(wait_ms)


def ride(sess: ShotSession, url: str, pts: Points) -> None:
    _open(sess, url)
    _move(sess, pts.a, wait_ms=0)
    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)
    sess.wait_for_results()
    coords = _route_coords(sess)
    sess.page.locator(".card.selected [data-ride-route]").click()
    sess.page.wait_for_selector("#nav:not(.hidden)")

    for f in (0.05, 0.15, 0.3, 0.4):
        _move(sess, _along(coords, f))
    instr = sess.page.inner_text("#nav-instr")
    sess.check("Banner shows next instruction", instr not in ("", "Waiting for GPS…"), instr)
    sess.check("Distance to next turn shown", sess.page.inner_text("#nav-dist").strip() != "")
    meta = sess.page.inner_text("#nav-meta")
    sess.check("Remaining distance and progress shown", "to go" in meta and "%" in meta, meta)
    sess.check("Position dot drawn", sess.page.locator("path.leaflet-interactive, canvas").count() > 0)
    sess.check("Sheet collapsed while riding", "collapsed" in (sess.page.get_attribute("#panel", "class") or ""))
    sess.shot("riding", "Riding a route on a phone: big next-turn banner, distance, progress; sheet tucked away.")

    here = _along(coords, 0.4)
    away = destination(here[0], here[1], 90, 250)
    for _ in range(4):
        _move(sess, away, wait_ms=700)
    warn = sess.page.inner_text("#nav-warn")
    sess.check("Off-route warning after repeated fixes", "Off route" in warn, warn)
    sess.check("Stale turn instruction replaced while off route",
               "Off route" in sess.page.inner_text("#nav-instr"))
    sess.check("Reroute button offered", sess.page.locator("#nav-reroute:not(.hidden)").count() == 1)
    sess.shot("off_route", "Leaving the route: warning after 3 consecutive off-route fixes, Reroute offered.")

    sess.page.click("#nav-reroute")
    sess.page.wait_for_timeout(2500)
    sess.check("Rerouted from current position",
               "rerouted" in sess.page.evaluate("window.cycleRoutes.rider.route.title"))
    sess.check("Warning cleared after reroute", "Off route" not in sess.page.inner_text("#nav-warn"))
    sess.shot("rerouted", "Reroute: a new route from where you are to the same destination; guidance continues.")

    new_coords = _route_coords(sess)
    for f in (0.5, 0.8, 1.0):
        _move(sess, _along(new_coords, f))
    sess.check("Arrival detected", "arrived" in sess.page.inner_text("#nav-instr"))
    sess.check("Stop becomes Finish", sess.page.inner_text("#nav-stop") == "Finish ride")
    sess.shot("arrived", "Arrival at the destination.")

    sess.page.click("#nav-stop")
    sess.page.wait_for_selector(".ride-summary", timeout=60000)
    sess.page.wait_for_timeout(800)
    summary = sess.page.inner_text(".ride-summary")
    sess.check("Ride summary with distance and ratings", "km" in summary and "Safety" in summary, summary[:120])
    sess.check("Ridden distance is not zero", " 0 km" not in summary, summary[:80])
    sess.check("Matched streets drawn as a rated route", sess.page.locator(".card:not(.ride-summary)").count() == 1)
    sess.shot("ride_saved", "After finishing: GPS stats plus ratings of the streets actually ridden.")

    sess.page.click("[data-tab=rides]")
    sess.page.wait_for_selector(".card.ride")
    sess.expect_count(".card.ride", 1, "Ride appears in My rides")
    sess.page.locator(".card.ride").first.locator("[data-act=show]").click()
    sess.page.wait_for_timeout(1500)
    sess.check("Recorded track drawn", sess.page.locator("path[stroke-dasharray]").count() >= 1)
    sess.shot("my_rides", "My rides: history with ratings, GPX/CSV export, and the track shown on the map.")

    rid = sess.page.evaluate("+document.querySelector('.card.ride').dataset.ride")
    gpx = sess.page.request.get(f"{url}api/rides/{rid}.gpx")
    sess.check("Recorded ride exports as GPX with timestamps", gpx.status == 200 and b"<time>" in gpx.body())
    sess.page.request.delete(f"{url}api/rides/{rid}")   # leave no test data behind
