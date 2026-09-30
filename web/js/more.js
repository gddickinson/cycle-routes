// "More" tab: network score, data sources, regions (switch / build), GPS source.

import { $, api, esc, post } from "./util.js";

const SOURCE_LABELS = {
  elevation: "Elevation (USGS 3DEP lidar)", canopy: "Tree shade (Meta/WRI canopy)", noise: "Noise (US DOT)",
  aadt: "Traffic volumes (TxDOT counts)", comfort: "City bike-comfort ratings (Austin)",
  crashes: "Bike crashes (Austin Vision Zero)", counters: "Bike counters (Austin)", stops: "Places (Overture Maps)",
};

export class More {
  constructor(app) {
    this.app = app;
    $("#region-build").addEventListener("click", () => this.build());
    this.loaded = false;
  }

  async load() {
    if (this.loaded) return;
    this.loaded = true;
    const src = this.app.region.sources || {};
    const always = ["Streets, paths, bike lanes, signed routes: OpenStreetMap", "Weather: Open-Meteo (CC BY 4.0)",
      "Live road works: City of Austin WZDx feed", "Bike share: CapMetro GBFS", "Place search: Nominatim"];
    $("#sources").innerHTML = always.map((s) => `<div>• ${esc(s)}</div>`).join("") +
      Object.entries(src).map(([k, v]) => `<div>• ${esc(SOURCE_LABELS[k] || k)}: <span class="muted">${esc(v)}</span></div>`).join("");
    this.regions();
    try {
      const s = await api("/api/network/score");
      $("#network-score").innerHTML = `<b>Low-stress network score: ${s.score}/100</b><br>${esc(s.explanation)}
        ${s.median_detour ? `Typical low-stress detour: ${Math.round((s.median_detour - 1) * 100)}%.` : ""}
        <br>${s.low_stress_km} of ${s.network_km} km of streets are low-stress (LTS 1–2).`;
    } catch (err) { $("#network-score").textContent = err.message; }
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
