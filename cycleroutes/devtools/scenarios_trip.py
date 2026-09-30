"""Trip builder (length + stops) for A→B and loops; voice settings."""

from cycleroutes.devtools.scenarios import Points, _open, frame
from cycleroutes.devtools.session import ShotSession


def trip_builder(sess: ShotSession, url: str, pts: Points) -> None:
    page = sess.page
    _open(sess, url)
    frame(sess, [pts.a, pts.b])
    page.wait_for_timeout(800)
    sess.click_map(*pts.a)
    sess.click_map(*pts.b)
    sess.wait_for_results()
    page.wait_for_timeout(1200)
    page.click("#ab-trip summary")
    page.check("#ab-length-on")
    page.fill("#ab-length", "20")
    page.dispatch_event("#ab-length", "input")
    page.locator("#ab-trip [data-stop=cafe]").click()
    page.locator("#ab-trip [data-stop=water]").click()
    page.locator("#ab-trip [data-stop=water]").click()
    sess.check("Stop chips count taps", "×2" in page.inner_text("#ab-trip [data-stop=water]"))
    page.click("#trip-go")
    page.wait_for_function("() => document.querySelector('.card.selected .tour-stops')", timeout=60000)
    page.wait_for_timeout(1500)
    km = float(page.inner_text(".card.selected .card-sub").split(" km")[0])
    sess.check("Trip stretched to about 20 km", 13 <= km <= 27, f"{km} km")
    stops = page.inner_text(".card.selected .tour-stops")
    sess.check("Café and water stops on the way", "Café" in stops and "Drinking water" in stops, stops[:120])
    sess.check("Stop pins on the map", page.locator(".stop-pin").count() >= 2)
    sess.shot("trip_ab", "Trip builder: about 20 km from A to B with a café half-way and two water stops.")

    page.click("[data-tab=loop]")
    frame(sess, [pts.loop])
    page.wait_for_timeout(800)
    sess.click_map(*pts.loop)
    page.fill("#loop-km", "25")
    page.dispatch_event("#loop-km", "input")
    for stop in ("cafe", "park", "treat"):
        page.locator(f"[data-body=loop] [data-stop={stop}]").click()
    page.click("#loop-go")
    page.wait_for_function("() => document.querySelector('.card.selected .tour-stops')", timeout=90000)
    page.wait_for_timeout(1500)
    sess.expect_count(".card", 1, "Loops with stops generated")
    sess.shot("trip_loop", "25 km loop with a café, a park and an ice-cream stop, spread along the way.")

    page.click("[data-tab=more]")
    page.wait_for_selector("#v-voice")
    n = page.locator("#v-voice option").count()
    sess.check("Voice choices listed", n >= 2, f"{n} options")
    page.select_option("#v-detail", "chatty")
    page.click("#v-test")
    page.wait_for_timeout(600)
    spoken = page.evaluate("window.__spoken || []")
    sess.check("Test voice speaks (captured silently in tests)", any("200 metres" in s for s in spoken), str(spoken))
    sess.shot("voice", "Voice guidance: voice, speed, pitch, volume, how much it says, chime, test.",
              element="#panel", tall=True)
