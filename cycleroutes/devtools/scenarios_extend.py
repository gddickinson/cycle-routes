"""Get to a suggested ride from somewhere else, make it a loop, save and reopen it."""

from cycleroutes.devtools.scenarios import Points, _open, frame
from cycleroutes.devtools.session import ShotSession


def extend_suggested(sess: ShotSession, url: str, pts: Points) -> None:
    page = sess.page
    _open(sess, url)
    page.click("[data-tab=suggested]")
    sess.wait_for_results()
    page.wait_for_timeout(1200)        # let the map's fit-to-route animation finish (taps are ignored meanwhile)
    card = page.locator(".card.selected")
    card.locator("[data-act=extend]").click()
    sess.check("Extend form opens", page.locator(".extend:not(.hidden)").count() == 1)
    card.locator("[data-x=pick-start]").click()
    frame(sess, [pts.a])
    page.wait_for_timeout(600)
    sess.check("Map asks for a point", "Tap your start" in page.inner_text("#status"))
    sess.click_map(*pts.a)
    page.wait_for_timeout(300)
    sess.check("Start chosen", "Start:" in card.locator("[data-x=start-label]").inner_text())
    card.locator("input[value=return]").check()
    sess.shot("extend_form", "🧭 Get there / extend: start from a point, join the ride, then return (a loop).",
              element=".card.selected", tall=True)
    card.locator("[data-x=go]").click()
    page.wait_for_function("() => document.querySelector('.card.selected .legs')", timeout=60000)
    page.wait_for_timeout(1500)
    legs = page.inner_text(".card.selected .legs")
    sess.check("Combined route shows its parts", "Getting there" in legs and "The route" in legs and "Onward" in legs, legs)
    dashed = page.evaluate("""() => { let n = 0; window.cycleRoutes.map.eachLayer(l => {
        if (l.options && l.options.dashArray === '9 7') n++; }); return n; }""")    # routes are drawn on a canvas
    sess.check("Getting-there and return parts drawn dashed", dashed >= 2, f"{dashed} dashed segments")
    sess.shot("extended", "Combined route: dashed getting there and back, the suggested ride solid in between.")

    page.locator(".card.selected [data-act=save]").click()
    page.wait_for_timeout(600)
    page.click("[data-tab=rides]")
    page.click("#favs-go")
    page.wait_for_selector("[data-plan]")
    page.locator("[data-plan]").first.click()
    page.wait_for_selector(".card.selected .legs", timeout=30000)
    sess.check("Saved combined route reopens exactly", "Getting there" in page.inner_text(".card.selected .legs"))
    sess.shot("reopened", "Saved routes reopen exactly as saved (including suggested and combined routes).")
    fav_ids = page.evaluate("fetch('/api/favourites').then(r => r.json()).then(f => f.map(x => x.id))")
    for fid in fav_ids:
        page.request.delete(f"{url}api/favourites/{fid}")
