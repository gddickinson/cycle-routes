// Optional data layers (crashes, counters, work zones, bike share, stops, hazards) and
// the press-and-hold map menu (report hazard, rate street, save place, set points).

import { $, api, esc, post, recall, remember } from "./util.js";

const L = window.L;
const STOP_EMOJI = { cafe: "☕", treat: "🍦", food: "🌮", shop: "🛒", bike_shop: "🔧", park: "🌳",
  landmark: "📷", swim: "🏊", stay: "🛏" };

const LAYERS = {
  stress: { label: "Traffic stress on every street" },
  trails: { label: "Cycle trails (green paved, brown unpaved, red = MTB grade 2+)" },
  amenities: { label: "Water, toilets, bike shops, parking" },
  stops: { label: "Cafés, food, sights (Overture)", minZoom: 15 },
  bikeshare: { label: "Bike share - live availability" },
  workzones: { label: "Road works (live): purple = closed, orange = lanes cut" },
  crashes: { label: "Bike crashes, last 7 years (Vision Zero)" },
  counters: { label: "Bike counters (bikes per day)" },
  hazards: { label: "Hazards reported by riders" },
};

function pin(html, cls = "") {
  return L.divIcon({ className: "", iconSize: [24, 24], html: `<div class="poi ${cls}">${html}</div>` });
}

export class Layers {
  constructor(app) {
    this.app = app;
    this.map = app.rmap.map;
    this.active = {};
    this.data = {};
    this.hazardTypes = {};
    const saved = recall("layers", {});
    $("#layer-toggles").innerHTML = Object.entries(LAYERS).map(([k, l]) =>
      `<label class="toggle"><input type="checkbox" data-layer="${k}" ${saved[k] ? "checked" : ""}> ${esc(l.label)}</label>`).join("");
    document.querySelectorAll("[data-layer]").forEach((cb) => {
      cb.addEventListener("change", () => this.toggle(cb.dataset.layer, cb.checked));
      if (cb.checked) this.toggle(cb.dataset.layer, true);
    });
    this.map.on("zoomend", () => { if (this.active.stops) this.draw("stops"); });
    this.map.on("contextmenu", (e) => this.menu(e.latlng));
    api("/api/hazard-types").then((t) => { this.hazardTypes = t; }).catch(() => {});
  }

  async toggle(name, on) {
    const saved = recall("layers", {});
    saved[name] = on;
    remember("layers", saved);
    if (name === "stress") return this.app.rmap.toggleStress(on);
    if (name === "amenities") return this.app.rmap.toggleAmenities(on);
    if (this.active[name]) { this.active[name].remove(); delete this.active[name]; }
    if (!on) return;
    try {
      this.data[name] = await api(`/api/layers/${name}`);
    } catch (err) { this.app.setStatus(err.message, true); return; }
    this.draw(name);
  }

  async reload(name) {
    if (!this.active[name]) return;
    this.data[name] = await api(`/api/layers/${name}`);
    this.draw(name);
  }

  draw(name) {
    if (this.active[name]) this.active[name].remove();
    const z = this.map.getZoom();
    const minZoom = LAYERS[name].minZoom || 0;
    const geo = this.data[name];
    const layer = L.geoJSON(z >= minZoom ? geo : { type: "FeatureCollection", features: [] }, {
      pointToLayer: (f, ll) => this.point(name, f.properties, ll),
      style: (f) => name === "trails"
        ? { color: f.properties.mtb >= 2 ? "#c0392b" : f.properties.paved ? "#1a7f37" : "#8b5a2b",
            weight: 4, opacity: 0.9, dashArray: f.properties.paved ? null : "6 4" }
        : name === "workzones"
        ? { color: f.properties.closed ? "#7a1fa2" : "#f0a202", weight: f.properties.closed ? 5 : 3,
            dashArray: f.properties.closed ? "10 6" : "4 5", opacity: 0.9 } : {},
      onEachFeature: (f, lyr) => lyr.bindPopup(() => this.popup(name, f.properties)),
    }).addTo(this.map);
    this.active[name] = layer;
  }

  point(name, p, ll) {
    if (name === "crashes") {
      return L.circleMarker(ll, { radius: p.severe ? 6 : 4, color: "#fff", weight: 1,
        fillColor: p.fatal ? "#000" : "#d1343a", fillOpacity: 0.85 });
    }
    if (name === "counters") return L.marker(ll, { icon: pin(`${p.bikes_per_day}`, "poi-count") });
    if (name === "bikeshare") return L.marker(ll, { icon: pin(`🚲<sub>${p.bikes}</sub>`, p.bikes ? "" : "poi-empty") });
    if (name === "hazards") return L.marker(ll, { icon: pin("⚠", "poi-hazard") });
    return L.marker(ll, { icon: pin(STOP_EMOJI[p.category] || "•") });
  }

  popup(name, p) {
    if (name === "crashes") return `<b>Bike crash ${esc(p.date)}</b><br>${p.fatal ? "Fatal" : p.severe ? "Serious injury" : "Crash"}<br>${esc(p.where)}`;
    if (name === "counters") return `<b>${esc(p.name)}</b><br>≈${p.bikes_per_day} bikes/day (last 60 days)`;
    if (name === "trails") return `<b>${esc(p.name || "Trail")}</b><br>${p.paved ? "Paved" : "Unpaved"}${p.mtb != null ? ` · MTB grade ${p.mtb}` : ""} · ${p.km} km segment`;
    if (name === "workzones") return `<b>${p.closed ? "Road closed" : "Lanes restricted"}</b><br>${esc(p.road)}<br>until ${esc(p.until)}`;
    if (name === "bikeshare") return `<b>${esc(p.name)}</b><br>${p.bikes} bikes (${p.ebikes} e-bikes) · ${p.docks} docks`;
    if (name === "hazards") {
      const div = document.createElement("div");
      div.innerHTML = `<b>${esc(p.label)}</b><br>${esc(p.note || "")}<br><small>reported ${new Date(p.created * 1000).toLocaleDateString()}
        · confirmed ${p.confirmations}×</small><div class="popup-btns"><button data-a="confirm">Still there</button>
        <button data-a="resolve">Gone</button></div>`;
      div.querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
        await post(`/api/hazards/${p.id}/${b.dataset.a}`);
        this.map.closePopup();
        this.reload("hazards");
        this.app.settings.refreshConditions();
      }));
      return div;
    }
    return `<b>${esc(p.name)}</b><br>${esc((p.kind || p.category || "").replace(/_/g, " "))}${p.website ? `<br><a href="${esc(p.website)}" target="_blank" rel="noopener">website</a>` : ""}`;
  }

  // --- press-and-hold menu ------------------------------------------------------------
  menu(latlng) {
    const ll = [latlng.lat, latlng.lng];
    const div = document.createElement("div");
    div.className = "ctx-menu";
    const types = Object.entries(this.hazardTypes).map(([k, t]) => `<option value="${k}">${esc(t.label)}</option>`).join("");
    div.innerHTML = `<div class="popup-btns">
        <button data-a="start">Start here</button><button data-a="end">End here</button>
        <button data-a="via">Add stop</button><button data-a="loop">Loop from here</button></div>
      <div class="popup-btns"><button data-a="up">👍 Good street</button><button data-a="down">👎 Bad street</button></div>
      <details><summary>Report a hazard here</summary><select data-f="kind">${types}</select>
        <input data-f="note" placeholder="Details (optional)" maxlength="300"><button data-a="hazard">Report</button></details>
      <details><summary>Save as a place</summary><input data-f="place" placeholder="e.g. Home, Work">
        <button data-a="place">Save</button></details>`;
    const popup = L.popup({ minWidth: 230 }).setLatLng(latlng).setContent(div).openOn(this.map);
    div.querySelectorAll("button[data-a]").forEach((b) => b.addEventListener("click", async () => {
      const a = b.dataset.a;
      try {
        if (a === "start" || a === "end") this.app.pointFromMenu(a, ll);
        else if (a === "via") this.app.plan.addVia(ll);
        else if (a === "loop") this.app.loopFromMenu(ll);
        else if (a === "up" || a === "down") {
          const r = await post("/api/feedback", { lat: ll[0], lon: ll[1], score: a === "up" ? 1 : -1 });
          this.app.setStatus(`Thanks - ${r.street} will be ${r.score > 0 ? "favoured" : "avoided"} a little more.`);
        } else if (a === "hazard") {
          const r = await post("/api/hazards", { lat: ll[0], lon: ll[1],
            kind: div.querySelector("[data-f=kind]").value, note: div.querySelector("[data-f=note]").value });
          this.app.setStatus(r.message);
          this.reload("hazards");
          this.app.settings.refreshConditions();
        } else if (a === "place") {
          await post("/api/places", { lat: ll[0], lon: ll[1], name: div.querySelector("[data-f=place]").value || "Place" });
          this.app.plan.loadPlaces();
          this.app.setStatus("Place saved - it's now a one-tap start/end.");
        }
        this.map.closePopup(popup);
      } catch (err) { this.app.setStatus(err.message, true); }
    }));
  }
}
