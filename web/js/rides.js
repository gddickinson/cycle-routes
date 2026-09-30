// "My rides": recorded rides with GPS stats, ratings of the streets ridden, exports.

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const RATING_LABELS = [["safety", "Safety"], ["fun", "Fun"], ["traffic", "Low traffic"], ["hills", "Easy climbing"]];

function when(ts) {
  return new Date(ts * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function summaryHtml(s) {
  if (!s) return `<div class="card-sub">Still recording (or not finished)</div>`;
  const ratings = s.ratings ? `<div class="ride-ratings">${RATING_LABELS.map(([k, l]) =>
    `<span class="tag">${l} <b>${s.ratings[k]}</b></span>`).join("")}</div>` : "";
  const matched = s.on_network_pct != null && s.on_network_pct < 60
    ? `<div class="facts">Only ${s.on_network_pct}% of the track matched mapped streets, so ratings are partial.</div>` : "";
  const odd = s.avg_moving_kmh > 60
    ? `<div class="facts">Average ${s.avg_moving_kmh} km/h is not a cycling speed - a vehicle, or a simulated track?</div>` : "";
  return `${odd}<div class="card-sub">${s.distance_km} km · ${s.moving_min} min moving · avg ${s.avg_moving_kmh} km/h ·
    max ${s.max_kmh} km/h${s.ascent_m != null ? ` · ↑${s.ascent_m} m` : ""}</div>${ratings}${matched}`;
}

export function renderRides(container, rides, { onShow, onDelete }) {
  if (!rides.length) {
    container.innerHTML = `<p class="muted">No rides yet. Press <b>Record a ride</b>, or choose
      <b>Ride this route</b> on any planned route. Your phone's GPS (or a USB GPS on the server) is used.</p>`;
    return;
  }
  container.innerHTML = rides.map((r) => `
    <article class="card ride" data-ride="${r.id}">
      <div class="card-head"><span class="card-title">${esc(r.name)}</span>
        ${r.summary?.ratings ? `<span class="card-score" title="Overall rating of the streets ridden">${r.summary.ratings.overall}</span>` : ""}</div>
      <div class="facts">${when(r.started)} · ${r.n_points} GPS points · ${esc(r.source || "")}</div>
      ${summaryHtml(r.summary)}
      <div class="actions">
        <button class="btn small secondary" data-act="show">Show on map</button>
        <a class="btn small secondary" href="/api/rides/${r.id}.gpx" download>GPX</a>
        <a class="btn small secondary" href="/api/rides/${r.id}.csv" download>CSV</a>
        <button class="btn small secondary danger" data-act="delete">Delete</button>
      </div>
    </article>`).join("");
  container.querySelectorAll(".card.ride").forEach((card) => {
    const id = +card.dataset.ride;
    card.querySelector("[data-act=show]").addEventListener("click", () => onShow(id));
    const del = card.querySelector("[data-act=delete]");
    del.addEventListener("click", () => {
      if (del.dataset.armed) { onDelete(id); return; }   // two taps: no browser confirm() dialog
      del.dataset.armed = "1";
      del.textContent = "Tap again to delete";
      setTimeout(() => { delete del.dataset.armed; del.textContent = "Delete"; }, 4000);
    });
  });
}
