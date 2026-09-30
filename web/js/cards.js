// Result cards: rating bars, stress mix, facts from open data, elevation, cue sheet,
// and actions (ride, print, GPX, save, share link).

import { esc } from "./util.js";

const RATINGS = [
  ["safety", "Safety"], ["fun", "Fun & scenery"], ["traffic", "Low traffic"],
  ["hills", "Easy climbing"], ["speed", "Speed"], ["surface", "Surface"], ["shade", "Shade"],
];

function barColor(v) {
  if (v >= 7.5) return "#1a7f37";
  if (v >= 5) return "#72b043";
  if (v >= 3) return "#f0a202";
  return "#d1343a";
}

function ratingBars(ratings, mode) {
  return RATINGS.filter(([k]) => ratings[k] != null).map(([k, label0]) => {
    const label = mode === "walk" ? ({ fun: "Pleasant", traffic: "Quiet", surface: "Paths & sidewalks" }[k] || label0) : label0;
    const v = ratings[k];
    return `<span>${label}</span><span class="bar"><i style="width:${v * 10}%;background:${barColor(v)}"></i></span><b>${v}</b>`;
  }).join("");
}

function stressMix(pct, colors) {
  return Object.entries(pct).filter(([, v]) => v > 0)
    .map(([lts, v]) => `<i title="LTS ${lts}: ${v}%" style="width:${v}%;background:${colors[lts]}"></i>`).join("");
}

export function elevationSvg(points) {
  if (!points || points.length < 2) return "";
  const W = 320, H = 70, pad = 2;
  const xs = points.map((p) => p[0]), zs = points.map((p) => p[1]);
  const x1 = xs[xs.length - 1] || 1;
  const zMin = Math.min(...zs) - 3, zMax = Math.max(...zs) + 3;
  const X = (x) => pad + (x / x1) * (W - 2 * pad);
  const Y = (z) => H - pad - ((z - zMin) / (zMax - zMin || 1)) * (H - 2 * pad);
  const line = points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  return `<svg class="elev" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
    aria-label="Elevation from ${Math.round(Math.min(...zs))} to ${Math.round(Math.max(...zs))} m">
    <path class="fill" d="${line}L${X(x1)},${H}L${X(0)},${H}Z"/><path class="line" d="${line}"/></svg>
    <div class="facts">${Math.round(Math.min(...zs))}–${Math.round(Math.max(...zs))} m elevation</div>`;
}

function walkFacts(s) {
  if (s.mode !== "walk") return "";
  const f = [`${s.sidewalk_pct}% on sidewalks or paths`];
  if (s.no_sidewalk_pct) f.push(`⚠ ${s.no_sidewalk_pct}% on streets without sidewalks`);
  f.push(`${s.accessible_pct}% step-free & gentle`);
  if (s.steps) f.push(`${s.steps} flight${s.steps > 1 ? "s" : ""} of steps`);
  if (s.lively_pct) f.push(`${s.lively_pct}% on lively streets`);
  if (s.sights_pct) f.push(`${s.sights_pct}% past sights`);
  if (s.ped_crashes) f.push(`${s.ped_crashes} pedestrian crash${s.ped_crashes > 1 ? "es" : ""} recorded on these streets`);
  return `<div class="facts">${f.map(esc).join(" · ")}</div>`;
}

function tourList(r) {
  if (!r.tour?.length) return "";
  return `<ol class="tour-stops">${r.tour.map((t) => `<li><b>${esc(t.name)}</b> <small>${esc((t.kind || "").replace(/_/g, " "))}</small></li>`).join("")}</ol>`;
}

function dataFacts(s) {
  const f = [];
  if (s.avoided_km) f.push(`⚠ ${s.avoided_km} km on road types you chose to avoid (no alternative)`);
  if (s.trail_pct) f.push(`${s.trail_pct}% on trails${s.max_mtb_scale != null ? ` (MTB grade up to ${s.max_mtb_scale})` : ""}`);
  if (s.crashes != null && s.mode !== "walk") f.push(`${s.crashes} recorded bike crash${s.crashes === 1 ? "" : "es"} on these streets${s.crashes_severe ? ` (${s.crashes_severe} serious)` : ""}`);
  if (s.risky_crossings) f.push(`${s.risky_crossings} unsignalised crossing${s.risky_crossings > 1 ? "s" : ""} of busy roads`);
  if (s.busiest_aadt) f.push(`busiest road ≈${s.busiest_aadt.toLocaleString()} vehicles/day`);
  if (s.avg_noise_db) f.push(`average noise ${s.avg_noise_db} dB`);
  return f.length ? `<div class="facts">${f.map(esc).join(" · ")}</div>` : "";
}

function details(r, colors) {
  const s = r.stats;
  const routes = s.signed_routes.length ? `<div class="facts">Signed routes: ${s.signed_routes.map(esc).join(", ")}</div>` : "";
  const cues = r.cues.map((c) => `<li><span class="dot" style="background:${colors[c.lts]}"></span>
    <span class="km">${c.at_km.toFixed(2)} km</span><span>${esc(c.instruction)}</span></li>`).join("");
  const ride = r.kind !== "ride" ? `<button class="btn small primary" data-act="ride">▶ ${r.mode === "walk" ? "Walk" : "Ride"} this route</button>` : "";
  return `<div class="details">
    ${elevationSvg(r.elevation)}
    <div class="facts">↑ ${s.ascent_m} m · ↓ ${s.descent_m} m · max ${s.max_grade_pct}% ·
      ${s.bike_infra_pct}% bike infrastructure · ${s.scenic_pct}% by parks/water</div>
    ${tourList(r)}${walkFacts(s)}${dataFacts(s)}${routes}
    <div class="actions">${ride}
      <select class="print-select" data-act="print" aria-label="Print">
        <option value="">🖨 Print…</option><option value="standard">Overview map</option>
        <option value="strip">Strip maps (long rides)</option><option value="card">Handlebar cue card (A6)</option>
        <option value="standard&scale=10000">Map at 1:10,000</option><option value="standard&scale=25000">Map at 1:25,000</option>
      </select>
      <a class="btn small secondary" href="/api/export/${r.id}.gpx" download>GPX</a>
      <button class="btn small secondary" data-act="save">★ Save</button>
      <button class="btn small secondary" data-act="link">🔗 Link</button>
    </div>
    <div class="extra" id="extra-${r.id}"><div class="facts">Loading stops and weather…</div></div>
    <ul class="cues">${cues}</ul>
  </div>`;
}

export function renderCards(container, routes, selectedId, colors, h) {
  container.innerHTML = routes.map((r) => {
    const s = r.stats;
    const also = r.also_best_for.length ? `<span class="tag">also ${esc(r.also_best_for.join(", "))}</span>` : "";
    const extra = s.distance_error_pct !== undefined && s.reuse_pct > 5 ? `<span class="tag">${s.reuse_pct}% ridden twice</span>` : "";
    const notice = s.notice ? `<div class="notice">${esc(s.notice)}</div>` : "";
    const ctx = s.context?.length ? `<div class="facts ctx">Planned for: ${esc(s.context.join(" · "))}</div>` : "";
    return `<article class="card ${r.id === selectedId ? "selected" : ""}" data-id="${r.id}">
      <div class="card-head"><span class="card-title">${esc(r.title)}</span>
        <span class="card-score" title="Overall rating">${s.ratings.overall}</span></div>
      <div class="card-sub">${s.distance_km} km · ~${Math.round(s.duration_min)} min ·
        ↑${s.ascent_m} m · ${s.hill_label}</div>
      ${notice}
      <div>${also}${extra}${r.mode === "walk" ? `<span class="tag">${s.sidewalk_pct}% sidewalks/paths</span>` : `<span class="tag">${s.signed_route_pct}% signed cycle route</span>`}</div>
      <div class="ratings">${ratingBars(s.ratings, r.mode)}</div>
      <div class="stress-mix" title="Share of route at each traffic-stress level">${stressMix(s.lts_pct, colors)}</div>
      ${r.id === selectedId ? ctx + details(r, colors) : ""}
    </article>`;
  }).join("");
  container.querySelectorAll(".card").forEach((el) => {
    const r = routes.find((x) => x.id === el.dataset.id);
    el.addEventListener("click", (ev) => {
      if (ev.target.closest("a, select, .extra")) return;
      const act = ev.target.closest("[data-act]")?.dataset.act;
      if (act === "ride") return h.onRide(r.id);
      if (act === "save") return h.onSave(r);
      if (act === "link") return h.onLink(r);
      h.onSelect(r.id);
    });
    const sel = el.querySelector(".print-select");
    if (sel) sel.addEventListener("change", () => {
      if (sel.value) window.open(`/api/export/${r.id}.pdf?layout=${sel.value}`, "_blank");
      sel.value = "";
    });
  });
  const selEl = container.querySelector(".card.selected");
  if (selEl) {
    scrollIntoScroller(selEl);
    h.onDetails?.(routes.find((x) => x.id === selectedId));
  }
}

function scrollIntoScroller(el) {
  let box = el.parentElement;
  while (box && !/(auto|scroll)/.test(getComputedStyle(box).overflowY)) box = box.parentElement;
  if (!box) return;
  const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  const sticky = box.querySelector(".panel-sticky");
  const offset = sticky && getComputedStyle(sticky).position === "sticky" ? sticky.offsetHeight + 8 : 8;
  box.scrollTo({ top: top - offset, behavior: "smooth" });
}
