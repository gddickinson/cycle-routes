// "More › Data sources": choose where each kind of data comes from for this area,
// reuse or refresh downloads, and apply the changes (re-score or rebuild).

import { $, api, esc, post } from "./util.js";

const when = (t) => new Date(t * 1000).toLocaleDateString();

export class SourcesPanel {
  constructor(app) { this.app = app; }

  async load() {
    let s;
    try { s = await api("/api/sources"); } catch (err) { $("#sources").textContent = err.message; return; }
    this.data = s;
    const opt = (sel, options, choice) => `<select id="${sel}">${Object.entries(options).map(([k, v]) =>
      `<option value="${k}" ${k === choice ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    const ex = s.network.extract_file;
    const layers = s.layers.map((l) => `<label class="toggle src-layer ${l.available ? "" : "na"}">
      <input type="checkbox" data-src-layer="${l.key}" ${l.enabled ? "checked" : ""} ${l.available ? "" : "disabled"}>
      <span>${esc(l.label)}${l.available ? "" : " <em>(not available here)</em>"}
      ${l.status ? `<small>${esc(l.status)}</small>` : ""}</span></label>`).join("");
    const downloads = s.downloads.map((d) => `<li>${esc(d.source)} · ${d.mb} MB · ${when(d.fetched)}</li>`).join("");
    $("#sources").innerHTML = `
      <div class="settings-grid">
        <label for="src-network">Streets</label>${opt("src-network", s.network.options, s.network.choice)}
        <span></span><small class="muted">In use: ${esc(s.network.current)}${ex ? ` · ${esc(ex.name)} ${ex.mb} MB, ${when(ex.downloaded)}` : ""}</small>
        <label for="src-elevation">Elevation</label>${opt("src-elevation", s.elevation.options, s.elevation.choice)}
        <span></span><small class="muted">In use: ${esc(s.elevation.current)}</small>
      </div>
      <div class="src-layers">${layers}</div>
      <label class="toggle strong"><input type="checkbox" id="src-cached" ${s.settings.prefer_cached ? "checked" : ""}>
        Use data already downloaded where it covers this area</label>
      <div class="row-btns wrap">
        <button id="src-apply" class="btn small primary">Apply changes</button>
        <button id="src-refresh" class="btn small secondary">Download fresh copies</button>
      </div>
      <div id="src-job" class="facts"></div>
      <details><summary class="muted">Stored downloads (${s.downloads.length})</summary><ul class="downloads">${downloads}</ul></details>
      <div class="facts">Live: ${s.live.filter(Boolean).map(esc).join(" · ")}</div>`;
    $("#src-apply").addEventListener("click", () => this.apply(false));
    $("#src-refresh").addEventListener("click", () => this.apply(true));
  }

  collect() {
    const layers = {};
    document.querySelectorAll("[data-src-layer]").forEach((cb) => { layers[cb.dataset.srcLayer] = cb.checked; });
    return { network: $("#src-network").value, elevation: $("#src-elevation").value,
      prefer_cached: $("#src-cached").checked, layers };
  }

  async apply(refresh) {
    try {
      const res = await post("/api/sources", { settings: this.collect(), apply: true, refresh });
      const job = res.job;
      $("#src-job").textContent = job.rebuild ? "Rebuilding the area (a few minutes)…" : "Applying…";
      const poll = async () => {
        const j = await api(`/api/sources/jobs/${job.id}`);
        $("#src-job").textContent = `${j.stage} (${Math.round(Date.now() / 1000 - j.started)} s)`;
        if (!j.done) setTimeout(poll, 2000);
        else if (!j.failed) { $("#src-job").textContent = "Done - reloading…"; setTimeout(() => location.reload(), 800); }
      };
      poll();
    } catch (err) { $("#src-job").textContent = err.message; }
  }
}
