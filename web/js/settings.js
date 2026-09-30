// Ride settings (bike type, departure time, weather/closure use), live conditions,
// and shareable links that encode a plan in the URL.

import { $, api, esc, recall, remember } from "./util.js";

export class Settings {
  constructor(region, onChange) {
    this.region = region;
    this.onChange = onChange;
    this.bike = recall("bike", "hybrid");
    this.depart = null;              // null = leave now
    this.weather = recall("weather", true);
    this.closures = recall("closures", true);
    this.mode = "bike";
    this.avoid = new Set(recall("avoid", []).filter((k) => k in (region.avoid_types || {})));
    this.infraOnly = recall("infraOnly", false);
    this.scoreData = recall("scoreData", "all");
    this.reports = recall("reports", true);
    $("#score-data").value = this.scoreData;
    $("#use-reports").checked = this.reports;
    $("#score-data").addEventListener("change", (e) => this.update({ scoreData: e.target.value }));
    $("#use-reports").addEventListener("change", (e) => this.update({ reports: e.target.checked }));
    this.renderAvoid();
    $("#infra-only").checked = this.infraOnly;
    $("#infra-only").addEventListener("change", (e) => this.update({ infraOnly: e.target.checked }));
    this.info = null;
    const sel = $("#bike-type");
    sel.innerHTML = Object.entries(region.bike_types)
      .map(([k, label]) => `<option value="${k}">${esc(label)}</option>`).join("");
    sel.value = this.bike in region.bike_types ? this.bike : "hybrid";
    $("#use-weather").checked = this.weather;
    $("#use-closures").checked = this.closures;
    sel.addEventListener("change", () => this.update({ bike: sel.value }));
    $("#depart").addEventListener("change", (e) => this.update({ depart: e.target.value || null }));
    $("#depart-now").addEventListener("click", () => { $("#depart").value = ""; this.update({ depart: null }); });
    $("#use-weather").addEventListener("change", (e) => this.update({ weather: e.target.checked }));
    $("#use-closures").addEventListener("change", (e) => this.update({ closures: e.target.checked }));
    this.refreshConditions();
  }

  renderAvoid() {
    const types = (this.mode === "walk" ? this.region.walk_avoid_types : this.region.avoid_types) || {};
    this.avoid = new Set([...this.avoid].filter((k) => k in types));
    $("#avoid-list").innerHTML = Object.entries(types).map(([k, label]) =>
      `<label class="toggle"><input type="checkbox" data-avoid="${k}" ${this.avoid.has(k) ? "checked" : ""}> ${esc(label)}</label>`).join("");
    document.querySelectorAll("[data-avoid]").forEach((cb) => cb.addEventListener("change", () => {
      if (cb.checked) this.avoid.add(cb.dataset.avoid); else this.avoid.delete(cb.dataset.avoid);
      this.update({});
    }));
  }

  setMode(mode) {
    this.mode = mode;
    this.avoid = new Set(recall(`avoid-${mode}`, []));
    this.renderAvoid();
    this.render();
  }

  update(changes) {
    Object.assign(this, changes);
    remember("bike", this.bike);
    remember("weather", this.weather);
    remember("closures", this.closures);
    remember(`avoid-${this.mode}`, [...this.avoid]);
    remember("infraOnly", this.infraOnly);
    remember("scoreData", this.scoreData);
    remember("reports", this.reports);
    this.refreshConditions();
    this.onChange?.();
  }

  query() {
    const q = new URLSearchParams({ bike: this.bike, weather: this.weather, closures: this.closures, mode: this.mode });
    if (this.depart) q.set("depart", this.depart);
    if (this.avoid.size) q.set("avoid", [...this.avoid].join(","));
    if (this.infraOnly) q.set("infra_only", "true");
    if (this.scoreData !== "all") q.set("data", this.scoreData);
    if (!this.reports) q.set("reports", "false");
    return q.toString();
  }

  async refreshConditions() {
    const q = new URLSearchParams({ bike: this.bike });
    if (this.depart) q.set("depart", this.depart);
    try {
      this.info = await api(`/api/conditions?${q}`);
    } catch { this.info = null; }
    this.render();
  }

  render() {
    const i = this.info;
    const when = this.depart ? new Date(this.depart).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) : "now";
    const w = i?.weather;
    const bits = [this.mode === "walk" ? "On foot" : (this.region.bike_types[this.bike] || "Hybrid"), when];
    if (w && this.weather) bits.push(`${Math.round(w.feels_c)}°C, wind ${w.wind_from} ${Math.round(w.wind_kmh)} km/h`);
    if (i?.dark) bits.push("🌙 dark");
    if (this.infraOnly && this.mode === "bike") bits.push("bike lanes only");
    if (this.avoid.size) bits.push(`avoiding ${this.avoid.size}`);
    if (this.scoreData === "osm") bits.push("OSM data only");
    $("#settings-summary").textContent = bits.join(" · ");
    if (!i) { $("#conditions").textContent = "Conditions unavailable."; return; }
    const lines = [`Sunrise ${i.sunrise} · sunset ${i.sunset}${i.dark ? " · riding in the dark: lit streets preferred" : ""}`];
    if (w) lines.push(`Feels like ${Math.round(w.feels_c)}°C · rain ${w.rain_pct ?? 0}% · gusts ${Math.round(w.gust_kmh || 0)} km/h · UV ${Math.round(w.uv || 0)}`);
    if (i.closures) lines.push(`${i.closures} street segments closed by roadworks right now (avoided)`);
    if (i.reports) lines.push(`${i.reports} hazard report${i.reports > 1 ? "s" : ""} from riders taken into account`);
    (i.advice || []).forEach((a) => lines.push(`⚠ ${a}`));
    $("#conditions").innerHTML = lines.map((l) => `<div>${esc(l)}</div>`).join("");
  }
}

// --- Share links: a plan encoded in the page URL -------------------------------------
export function planLink(params) {
  const q = new URLSearchParams();
  const pt = (p) => p.map((n) => Number(n).toFixed(5)).join(",");
  Object.entries(params).forEach(([k, v]) => {
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return;
    if (Array.isArray(v) && Array.isArray(v[0])) q.set(k, v.map(pt).join(";"));   // list of points
    else if (Array.isArray(v)) q.set(k, pt(v));                                     // one point
    else q.set(k, String(v));
  });
  return `${location.origin}/?${q}`;
}

export function readLink() {
  const q = new URLSearchParams(location.search);
  if (!q.has("start") && !q.has("loop")) return null;
  const pt = (s) => s.split(",").map(Number);
  return {
    start: q.get("start") ? pt(q.get("start")) : null,
    end: q.get("end") ? pt(q.get("end")) : null,
    via: q.get("via") ? q.get("via").split(";").map(pt) : [],
    loop: q.get("loop") ? pt(q.get("loop")) : null,
    km: q.get("km") ? Number(q.get("km")) : null,
    profile: q.get("profile"), bike: q.get("bike"),
  };
}
