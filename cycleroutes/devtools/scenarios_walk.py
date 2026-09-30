"""Walking mode: switch, A→B walk with walking facts, sightseeing tour, suggested walks, phone."""

from cycleroutes.devtools.scenarios import Points, _open, frame
from cycleroutes.devtools.session import ShotSession


def _route(sess: ShotSession, pts: Points) -> None:
    frame(sess, [pts.a, pts.b])
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)
    sess.wait_for_results()


def walking(sess: ShotSession, url: str, pts: Points) -> None:
    page = sess.page
    _open(sess, url)
    if not page.evaluate("fetch('/api/region').then(r => r.json()).then(d => d.walk_available)"):
        sess.check("Walking network built", False, "run: cycleroutes walk")
        sess.shot("not_built", "Walking routes not built for this area.")
        return
    page.click("[data-mode=walk]")
    page.wait_for_timeout(500)
    sess.check("Walk mode active", page.get_attribute("body", "data-mode") == "walk")
    sess.check("Bike-only controls hidden", not page.locator("#bike-type").is_visible())
    sess.check("Tab renamed to Walks", page.inner_text("[data-tab=rides]") == "Walks")
    _route(sess, pts)
    titles = page.locator(".card-title").all_inner_texts()
    sess.check("Walking trip types offered", any(t in titles for t in ("Commute", "Safest", "Green & quiet")), ", ".join(titles))
    card = page.locator(".card.selected")
    facts = " ".join(card.locator(".facts").all_inner_texts())
    sess.check("Walking facts shown", "sidewalks or paths" in facts and "step-free" in facts, facts[:160])
    sess.check("Walk this route button", card.locator("[data-act=ride]").inner_text().endswith("Walk this route"))
    sess.shot("walk_ab", "Walk mode: commute, safest, green, urban, sightseeing, step-free… each rated for walking.")

    page.click("[data-tab=loop]")
    frame(sess, [pts.loop])
    sess.click_map(*pts.loop)
    page.select_option("#loop-profile", "tour")
    page.fill("#loop-km", "5")
    page.dispatch_event("#loop-km", "input")
    page.click("#loop-go")
    sess.wait_for_results()
    n_pins = page.locator(".tour-pin").count()
    sess.check("Tour stops numbered on the map", n_pins >= 2, f"{n_pins} stops")
    sess.check("Tour stops listed on the card", page.locator(".tour-stops li").count() == n_pins)
    sess.shot("tour", "Sightseeing tour: the best-rated sights nearby, visited in a sensible order.")

    page.click("[data-tab=suggested]")
    sess.wait_for_results()
    sess.expect_count(".card", 1, "Suggested walks listed")
    sess.shot("suggested_walks", "Suggested walks: hikes, green & quiet strolls and urban adventures from parks and the centre.")
    page.click("[data-mode=bike]")                   # leave the app in bike mode for other scenarios
