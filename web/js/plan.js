// Planning extras: via points, saved places & favourites, stops/weather along a route,
// multi-day stages and the side-by-side comparison table.

import { $, api, del, esc, post } from "./util.js";

const GROUP_LABEL = { water: "💧 water", toilets: "🚻 toilets", bike: "🔧 bike shop", bike_share: "🚲 bike share",
  food: "☕ food & coffee", sights: "📷 sights", stay: "🛏 stay", parking: "🅿 parking" };
const COMPARE_ROWS = [
  ["Distance", (s) => `${s.distance_km} km`], ["Time", (s) => `${Math.round(s.duration_min)} min`],
  ["Climb", (s) => `${s.ascent_m} m`], ["Overall", (s) => s.ratings.overall], ["Safety", (s) => s.ratings.safety],
  ["Fun", (s) => s.ratings.fun], ["Low traffic", (s) => s.ratings.traffic], ["Shade", (s) => s.ratings.shade ?? "–"],
  ["Crashes on route", (s) => s.crashes ?? "–"], ["Busy crossings", (s) => s.risky_crossings ?? "–"],
  ["Busiest road (veh/day)", (s) => s.busiest_aadt ? s.busiest_aadt.toLocaleString() : "–"],
  ["Noise", (s) => s.avg_noise_db ? `${s.avg_noise_db} dB` : "–"], ["Bike infrastructure", (s) => `${s.bike_infra_pct}%`],
  ["On trails", (s) => `${s.trail_pct ?? 0}%`], ["Avoided road types", (s) => s.avoided_km != null ? `${s.avoided_km} km` : "–"],
];

export class Plan {
  constructor(app) {
    this.app = app;
    this.via = [];
    this.addingVia = false;
    $("#via-add").addEventListener("click", () => {
      this.addingVia = !this.addingVia;
      $("#via-add").classList.toggle("active", this.addingVia);
      app.setStatus(this.addingVia ? "Tap the map to add a stop on the way (drag stops to reshape the route)." : "");
    });
    $("#favs-go").addEventListener("click", () => this.showFavourites());
    this.loadPlaces();
  }

  // --- via points --------------------------------------------------------------------
  addVia(ll) {
    this.via.push(ll);
    this.addingVia = false;
    $("#via-add").classList.remove("active");
    this.renderVia();
    if (this.app.state.start && this.app.state.end) this.app.findAlternatives();
  }

  clearVia() { this.via = []; this.renderVia(); }

  renderVia() {
    $("#via-list").innerHTML = this.via.map((p, i) => `<div class="via-row"><span class="via-num">${i + 1}</span>
      Stop ${i + 1} <small>${p[0].toFixed(4)}, ${p[1].toFixed(4)}</small><button class="icon-btn" data-rm="${i}" title="Remove">✕</button></div>`).join("");
    document.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => {
      this.via.splice(+b.dataset.rm, 1);
      this.renderVia();
      if (this.app.state.start && this.app.state.end) this.app.findAlternatives();
    }));
    this.app.rmap.setVias(this.via, (i, p) => {
      this.via[i] = p;
      this.renderVia();
      this.app.findAlternatives();
    });
  }

  viaParam() {
    return this.via.length ? `&via=${this.via.map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`).join(";")}` : "";
  }

  // --- places & favourites -------------------------------------------------------------
  async loadPlaces() {
    const places = await api("/api/places").catch(() => []);
    $("#place-chips").innerHTML = places.map((p) => `<span class="chip" data-id="${p.id}">
      <button data-go="${p.id}">📍 ${esc(p.name)}</button><button data-del="${p.id}" title="Forget">✕</button></span>`).join("");
    places.forEach((p) => {
      $(`[data-go="${p.id}"]`).addEventListener("click", () => this.app.pointFromMenu(this.app.state.start && !this.app.state.end ? "end" : "start", [p.lat, p.lon], p.name));
      $(`[data-del="${p.id}"]`).addEventListener("click", async () => { await del(`/api/places/${p.id}`); this.loadPlaces(); });
    });
  }

  async saveFavourite(route) {
    await post("/api/favourites", { title: route.title, params: route.request || {} });
    this.app.setStatus("Saved - find it under Rides › Saved routes.");
  }

  async showFavourites() {
    const favs = await api("/api/favourites");
    const box = $("#results");
    if (!favs.length) { box.innerHTML = `<p class="muted">No saved routes yet - use ★ Save on any route.</p>`; return; }
    box.innerHTML = favs.map((f) => `<article class="card"><div class="card-head"><span class="card-title">${esc(f.title)}</span></div>
      <div class="facts">${new Date(f.created * 1000).toLocaleDateString()}</div>
      <div class="actions"><button class="btn small primary" data-plan="${f.id}">Plan again</button>
      <button class="btn small secondary danger" data-fdel="${f.id}">Delete</button></div></article>`).join("");
    favs.forEach((f) => {
      $(`[data-plan="${f.id}"]`).addEventListener("click", () => this.app.openPlan(f.params));
      $(`[data-fdel="${f.id}"]`).addEventListener("click", async () => { await del(`/api/favourites/${f.id}`); this.showFavourites(); });
    });
  }

  // --- stops, weather and stages for the selected route ---------------------------------
  async loadDetails(route) {
    const box = document.getElementById(`extra-${route.id}`);
    if (!box || box.dataset.loaded) return;
    box.dataset.loaded = "1";
    try {
      const [stops, wx] = await Promise.all([api(`/api/stops/${route.id}`),
        api(`/api/weather/${route.id}${this.app.settings.depart ? `?depart=${this.app.settings.depart}` : ""}`).catch(() => null)]);
      const chips = Object.entries(stops.counts).filter(([g]) => GROUP_LABEL[g])
        .map(([g, n]) => `<span class="tag">${GROUP_LABEL[g]} ${n}</span>`).join("");
      const water = stops.stops.filter((s) => ["water", "toilets", "bike", "bike_share"].includes(s.group)).slice(0, 12);
      box.innerHTML = `<div class="facts"><b>Along the way</b> (within 150 m)</div><div>${chips || '<span class="muted">nothing mapped</span>'}</div>
        <div class="facts">Longest stretch without water or food: ${stops.longest_without_water_km} km</div>
        ${water.length ? `<ul class="cues">${water.map((s) => `<li><span class="km">${s.at_km.toFixed(1)} km</span>
          <span>${esc(GROUP_LABEL[s.group] || s.group)} ${esc(s.name || s.label || "")}${s.bikes != null ? ` - ${s.bikes} bikes` : ""}</span></li>`).join("")}</ul>` : ""}
        ${wx?.advice?.length ? `<div class="advice">${wx.advice.map((a) => `⚠ ${esc(a)}`).join("<br>")}</div>` : ""}
        ${route.stats.distance_km > 30 ? `<div class="facts">Long ride: <button class="btn small secondary" data-stages="${route.id}">Split into days</button></div>` : ""}`;
      this.app.rmap.showStops(stops.stops.filter((s) => ["water", "toilets", "bike", "bike_share", "stay"].includes(s.group)));
      const sb = box.querySelector("[data-stages]");
      if (sb) sb.addEventListener("click", () => this.showStages(route, box));
    } catch (err) { box.innerHTML = `<div class="facts">${esc(err.message)}</div>`; }
  }

  async showStages(route, box) {
    const days = await api(`/api/stages/${route.id}?km_per_day=40`);
    box.insertAdjacentHTML("beforeend", `<ul class="cues">${days.map((d) => `<li><span class="km">Day ${d.day}</span>
      <span>${d.km} km, ↑${d.climb_m} m${d.stay ? ` → stay: ${esc(d.stay.name)}` : ""}</span></li>`).join("")}</ul>`);
  }

  // --- comparison ----------------------------------------------------------------------
  compareHtml(routes) {
    const head = routes.map((r) => `<th>${esc(r.title)}</th>`).join("");
    const rows = COMPARE_ROWS.map(([label, f]) => {
      const vals = routes.map((r) => f(r.stats));
      return `<tr><th>${label}</th>${vals.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`;
    }).join("");
    return `<div class="compare"><table><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }
}
