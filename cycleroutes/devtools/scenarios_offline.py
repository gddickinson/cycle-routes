"""Offline end-to-end: download the vector basemap, save map + data on the device,
then cut the network and reload - the app must still start and draw the map."""

from cycleroutes.devtools.scenarios import Points, _open, frame
from cycleroutes.devtools.session import ShotSession


def offline(sess: ShotSession, url: str, pts: Points) -> None:
    page = sess.page
    _open(sess, url)
    if not page.request.get(f"{url}api/offline/status").json().get("basemap"):
        # never overwrite a real (full-zoom) download: only fetch a quick one if none exists
        job = page.request.post(f"{url}api/offline/basemap?max_zoom=13").json()
        for _ in range(240):
            j = page.request.get(f"{url}api/offline/jobs/{job['id']}").json()
            if j["done"]:
                break
            page.wait_for_timeout(1000)
        sess.check("Offline map downloaded", j.get("done") and not j.get("failed"), j.get("stage", ""))

    _open(sess, url)                                  # reload so the page sees the stored map
    page.click("[data-tab=more]")
    page.wait_for_function("() => document.querySelector('#offline-status').textContent.includes('stored')")
    sess.check("Status shows the stored map", "tiles" in page.inner_text("#offline-status"))
    page.wait_for_function("() => navigator.serviceWorker && navigator.serviceWorker.controller", timeout=20000)
    page.click("#offline-save")
    page.wait_for_function("() => document.querySelector('#offline-progress').textContent.startsWith('Saved')",
                           timeout=180000)
    sess.check("Map and data saved on the device", "work offline" in page.inner_text("#offline-progress"))
    sess.shot("saved", "More › Offline: map downloaded and saved on this device, plus data export / import.",
              element="#panel", tall=True)

    sess.expect_offline = True
    page.context.set_offline(True)
    page.reload()
    page.wait_for_function("window.cycleRoutes !== undefined", timeout=30000)
    page.wait_for_timeout(2500)
    offline_layer = page.evaluate("!!window.cycleRoutes.app.rmap.offlineLayer && "
                                  "window.cycleRoutes.map.hasLayer(window.cycleRoutes.app.rmap.offlineLayer)")
    sess.check("App starts with no network", page.locator(".tab").count() == 5)
    sess.check("Offline basemap selected automatically", offline_layer)
    frame(sess, [pts.a, pts.b])
    page.wait_for_timeout(2500)
    painted = page.evaluate("""() => [...document.querySelectorAll('.leaflet-tile-container canvas, canvas.leaflet-tile')]
        .some(c => { try { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
          for (let i = 0; i < d.length; i += 4000) if (d[i + 3] > 0) return true; } catch (e) {} return false; })""")
    sess.check("Offline map tiles drawn", painted)
    sess.shot("offline_map", "No network: the app and the locally stored vector map still work.")
    page.context.set_offline(False)
    sess.expect_offline = False
