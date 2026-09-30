// Result cards: rating bars, stress mix, elevation profile, cue sheet, exports.

const RATINGS = [
  ["safety", "Safety"], ["fun", "Fun & scenery"], ["traffic", "Low traffic"],
  ["hills", "Easy climbing"], ["speed", "Speed"], ["surface", "Surface"],
];

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function barColor(v) {
  if (v >= 7.5) return "#1a7f37";
  if (v >= 5) return "#72b043";
  if (v >= 3) return "#f0a202";
  return "#d1343a";
}

function ratingBars(ratings) {
  return RATINGS.map(([k, label]) => {
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

function details(r, colors) {
  const s = r.stats;
  const routes = s.signed_routes.length ? `<div class="facts">Signed routes: ${s.signed_routes.map(esc).join(", ")}</div>` : "";
  const cues = r.cues.map((c) => `<li><span class="dot" style="background:${colors[c.lts]}"></span>
    <span class="km">${c.at_km.toFixed(2)} km</span><span>${esc(c.instruction)}</span></li>`).join("");
  return `<div class="details">
    ${elevationSvg(r.elevation)}
    <div class="facts">↑ ${s.ascent_m} m · ↓ ${s.descent_m} m · max ${s.max_grade_pct}% ·
      ${s.bike_infra_pct}% bike infrastructure · ${s.scenic_pct}% by parks/water</div>
    ${routes}
    <div class="actions">
      ${r.kind !== "ride" ? `<button class="btn small primary" data-ride-route="${r.id}">▶ Ride this route</button>` : ""}
      <a class="btn small secondary" href="/api/export/${r.id}.pdf" target="_blank">Print map (PDF)</a>
      <a class="btn small secondary" href="/api/export/${r.id}.gpx" download>GPX for bike computer</a>
    </div>
    <ul class="cues">${cues}</ul>
  </div>`;
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

export function renderCards(container, routes, selectedId, colors, onSelect, onRide = null) {
  container.innerHTML = routes.map((r) => {
    const s = r.stats;
    const also = r.also_best_for.length ? `<span class="tag">also ${esc(r.also_best_for.join(", "))}</span>` : "";
    const extra = s.distance_error_pct !== undefined && s.reuse_pct > 5
      ? `<span class="tag">${s.reuse_pct}% ridden twice</span>` : "";
    return `<article class="card ${r.id === selectedId ? "selected" : ""}" data-id="${r.id}">
      <div class="card-head"><span class="card-title">${esc(r.title)}</span>
        <span class="card-score" title="Overall rating">${s.ratings.overall}</span></div>
      <div class="card-sub">${s.distance_km} km · ~${Math.round(s.duration_min)} min ·
        ↑${s.ascent_m} m · ${s.hill_label}</div>
      <div>${also}${extra}<span class="tag">${s.signed_route_pct}% signed cycle route</span></div>
      <div class="ratings">${ratingBars(s.ratings)}</div>
      <div class="stress-mix" title="Share of route at each traffic-stress level">${stressMix(s.lts_pct, colors)}</div>
      ${r.id === selectedId ? details(r, colors) : ""}
    </article>`;
  }).join("");
  container.querySelectorAll(".card").forEach((el) => {
    el.addEventListener("click", (ev) => {
      if (ev.target.closest("a")) return;
      const rideBtn = ev.target.closest("[data-ride-route]");
      if (rideBtn) { if (onRide) onRide(rideBtn.dataset.rideRoute); return; }
      onSelect(el.dataset.id);
    });
  });
  const sel = container.querySelector(".card.selected");
  if (sel) scrollIntoScroller(sel);
}
