// Trip builder UI: target length + kinds of stops, for A→B trips and loops.

import { $, api, esc } from "./util.js";

const EMOJI = { cafe: "☕", treat: "🍦", food: "🌮", water: "💧", toilets: "🚻", park: "🌳", sight: "📷",
  bike_shop: "🔧", shop: "🛒", swim: "🏊", bike_share: "🚲" };

export class TripBuilder {
  constructor(app) {
    this.app = app;
    this.counts = {};
    api("/api/stop-types").then((types) => { this.types = types; this.render(); }).catch(() => {});
    $("#ab-length-on").addEventListener("change", (e) => { $("#ab-length").disabled = !e.target.checked; });
    $("#ab-length").addEventListener("input", (e) => { $("#ab-length-val").textContent = e.target.value; });
  }

  render() {
    const html = Object.entries(this.types).filter(([k]) => this.app.getMode() === "bike" || k !== "bike_shop")
      .map(([k, label]) => `<button class="stop-chip ${this.counts[k] ? "on" : ""}" data-stop="${k}" title="Tap to add more">
        ${EMOJI[k] || "•"} ${esc(label)}${this.counts[k] ? ` <b>×${this.counts[k]}</b>` : ""}</button>`).join("");
    document.querySelectorAll(".stop-chips").forEach((box) => { box.innerHTML = html; });
    document.querySelectorAll("[data-stop]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.stop;
      this.counts[k] = ((this.counts[k] || 0) + 1) % 4;     // 0 → 1 → 2 → 3 → 0
      this.render();
    }));
  }

  stops() {
    return Object.entries(this.counts).filter(([, n]) => n > 0).map(([type, count]) => ({ type, count }));
  }

  hasStops() { return this.stops().length > 0; }

  abTargetKm() { return $("#ab-length-on").checked ? +$("#ab-length").value : null; }
}

export function stopList(r) {
  if (!r.planned_stops?.length && !r.missing_stops?.length) return "";
  const items = (r.planned_stops || []).map((s) => `<li>${EMOJI[s.stop_type] || "•"} <b>${esc(s.name || s.stop_label)}</b>
    <small>${s.at_km.toFixed(1)} km · ${esc(s.stop_label)}</small></li>`).join("");
  const missing = r.missing_stops?.length ? `<div class="facts">⚠ No ${esc(r.missing_stops.join(", ").toLowerCase())} found near this route.</div>` : "";
  return `<ol class="tour-stops">${items}</ol>${missing}`;
}

export { EMOJI as STOP_EMOJI };
