// "More" tab: network score, data sources, regions (switch / build), GPS source.

import { SourcesPanel } from "./sources.js";
import { $, api, esc, post } from "./util.js";

export class More {
  constructor(app) {
    this.app = app;
    this.sources = new SourcesPanel(app);
    $("#region-build").addEventListener("click", () => this.build());
    $("#offline-download").addEventListener("click", () => this.downloadBasemap());
    $("#offline-save").addEventListener("click", () => this.saveOnDevice());
    $("#backup-file").addEventListener("change", (e) => this.importBackup(e.target.files[0]));
    navigator.serviceWorker?.addEventListener("message", (e) => {
      if (e.data?.type === "precache-progress") {
        const { done, total, failed } = e.data;
        $("#offline-progress").textContent = done < total
          ? `Saving on this device… ${done}/${total}` : `Saved ${total - failed} items on this device - the map and your routes now work offline.`;
      }
    });
    this.loaded = false;
    this.offlineStatus();
  }

  async load() {
    if (this.loaded) return;
    this.loaded = true;
    this.sources.load();
    this.regions();
    try {
      const s = await api("/api/network/score");
      $("#network-score").innerHTML = `<b>Low-stress network score: ${s.score}/100</b><br>${esc(s.explanation)}
        ${s.median_detour ? `Typical low-stress detour: ${Math.round((s.median_detour - 1) * 100)}%.` : ""}
        <br>${s.low_stress_km} of ${s.network_km} km of streets are low-stress (LTS 1–2).`;
    } catch (err) { $("#network-score").textContent = err.message; }
  }

  // --- offline map & local data --------------------------------------------------
  async offlineStatus() {
    const s = await api("/api/offline/status").catch(() => null);
    if (!s) return;
    const bm = s.basemap;
    $("#offline-status").innerHTML = bm
      ? `Offline map stored: ${bm.tiles} tiles, ${(bm.bytes / 1e6).toFixed(1)} MB (zoom ≤ ${bm.max_zoom}),
         ${new Date(bm.built * 1000).toLocaleDateString()}. Area data on this computer: ${s.region_data_mb} MB.`
      : `No offline map yet. Area data on this computer: ${s.region_data_mb} MB (street network, open-data layers, elevation).`;
    $("#offline-download").textContent = bm ? "Update offline map" : "Download offline map";
    $("#offline-save").disabled = !bm || !navigator.serviceWorker;
    if (bm) this.app.rmap.addOfflineBasemap(bm);
  }

  async downloadBasemap() {
    const job = await post("/api/offline/basemap");
    const poll = async () => {
      const j = await api(`/api/offline/jobs/${job.id}`);
      $("#offline-progress").textContent = j.stage;
      if (!j.done) setTimeout(poll, 1500);
      else this.offlineStatus();
    };
    poll();
  }

  async saveOnDevice() {
    const reg = await navigator.serviceWorker?.ready;
    if (!reg?.active) { $("#offline-progress").textContent = "Offline storage isn't available in this browser."; return; }
    const m = await api("/api/offline/manifest?min_zoom=10");
    $("#offline-progress").textContent = `Saving ${m.tiles.length} map tiles and your data on this device…`;
    try { await navigator.storage?.persist?.(); } catch { /* optional */ }
    reg.active.postMessage({ type: "precache", urls: [...m.api, ...m.tiles] });
  }

  async importBackup(file) {
    if (!file) return;
    try {
      const res = await post("/api/backup", JSON.parse(await file.text()));
      const n = res.imported;
      this.app.setStatus(`Imported ${n.rides} rides, ${n.places} places, ${n.favourites} saved routes, ${n.hazards} reports.`);
    } catch (err) { this.app.setStatus(`Import failed: ${err.message}`, true); }
  }

  async regions() {
    const list = await api("/api/regions").catch(() => []);
    $("#regions").innerHTML = list.length > 1 ? `<div class="facts">Areas: ${list.map((r) => r.active
      ? `<b>${esc(r.name)}</b>` : `<button class="btn small secondary" data-region="${esc(r.name)}">${esc(r.name)}</button>`).join(" ")}</div>` : "";
    document.querySelectorAll("[data-region]").forEach((b) => b.addEventListener("click", async () => {
      this.app.setStatus(`Switching to ${b.dataset.region}…`);
      await post(`/api/regions/${b.dataset.region}/activate`);
      location.reload();
    }));
  }

  async build() {
    const c = this.app.rmap.map.getCenter();
    const name = $("#region-name").value.trim();
    if (!name) { $("#region-job").textContent = "Give the area a name first."; return; }
    try {
      const job = await post("/api/regions/build", { name, lat: c.lat, lon: c.lng, radius_m: +$("#region-radius").value });
      this.poll(job.id);
    } catch (err) { $("#region-job").textContent = err.message; }
  }

  async poll(id) {
    const job = await api(`/api/regions/jobs/${id}`);
    const mins = Math.round((Date.now() / 1000 - job.started) / 60);
    $("#region-job").textContent = `${job.name}: ${job.stage} (${mins} min)`;
    if (!job.done) setTimeout(() => this.poll(id), 10000);
    else if (!job.failed) this.regions();
  }
}
