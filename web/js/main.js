// App wiring: tabs, place search, map clicks, API calls, results.

import { RouteMap } from "./map.js";
import { renderCards } from "./cards.js";
import { RideController } from "./ride.js";
import { renderRides, summaryHtml } from "./rides.js";

const $ = (sel) => document.querySelector(sel);
const fmt = (p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
const SLIDERS = [["safety", "Safety", 3], ["fun", "Fun", 1], ["traffic", "Low traffic", 1],
  ["hills", "Avoid hills", 1], ["surface", "Smooth", 0.5]];

const state = { tab: "ab", start: null, end: null, loopStart: null, routes: [], selected: null };
let region, rmap, rider;

function setStatus(text, error = false) {
  const el = $("#status");
  el.textContent = text;
  el.classList.toggle("error", error);
}

async function api(path) {
  const res = await fetch(path);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(out.detail || `Request failed (${res.status})`);
  return out;
}

function showResults(routes) {
  state.routes = routes;
  state.selected = routes.length ? routes[0].id : null;
  refresh(true);
}

function refresh(fit = false) {
  const bounds = rmap.showRoutes(state.routes, state.selected, select);
  renderCards($("#results"), state.routes, state.selected, region.lts_colors, select, rideRoute);
  if (fit) rmap.fit(bounds);
}

function select(id) {
  state.selected = id;
  refresh(true);
  $("#panel").classList.remove("collapsed");
}

async function run(label, fn) {
  setStatus(label);
  $("#results").innerHTML = "";
  try {
    const routes = await fn();
    setStatus(routes.length ? `${routes.length} option${routes.length > 1 ? "s" : ""} — tap one for details` : "Nothing found");
    showResults(routes);
  } catch (err) {
    setStatus(err.message, true);
  }
}

// --- Riding & recorded rides ------------------------------------------------------
function rideRoute(id) {
  const route = state.routes.find((r) => r.id === id);
  if (!route) return;
  state.routes = [route];
  state.selected = id;
  refresh(true);
  $("#panel").classList.add("collapsed");
  rider.start(route).catch((err) => setStatus(err.message, true));
}

function onRideFinished(result) {
  switchTab("rides", false);
  const s = result.summary;
  const matched = result.matched ? [result.matched] : [];
  state.routes = matched;
  state.selected = matched[0]?.id || null;
  refresh(true);
  $("#results").insertAdjacentHTML("afterbegin", `<article class="card ride-summary">
    <div class="card-title">Ride saved: ${result.ride.name}</div>${summaryHtml(s)}</article>`);
  $("#panel").classList.remove("collapsed");
  setStatus("Ride saved. The streets you rode are rated below.");
}

async function loadRides() {
  const rides = await api("/api/rides");
  renderRides($("#results"), rides, {
    onShow: async (id) => {
      const r = await api(`/api/rides/${id}`);
      // draw on the map only - keep the rides list in the panel
      rmap.showRoutes(r.matched ? [r.matched] : [], r.matched?.id, () => {});
      document.querySelectorAll(".card.ride").forEach((c) => c.classList.toggle("selected", +c.dataset.ride === id));
      const bounds = rmap.showTrack(r.track);
      rmap.fit(bounds);
      setStatus(`${r.ride.name}: blue dashes = GPS track, colours = streets matched`);
    },
    onDelete: async (id) => {
      await fetch(`/api/rides/${id}`, { method: "DELETE" });
      rmap.showTrack(null);
      loadRides();
    },
  });
  setStatus(rides.length ? `${rides.length} recorded ride${rides.length > 1 ? "s" : ""}` : "");
}

async function loadGpsSources() {
  const sources = await api("/api/gps/sources").catch(() => []);
  const extra = sources.filter((s) => s.key !== "phone")
    .map((s) => `<option value="${s.key}">${s.name}</option>`).join("");
  $("#gps-source").innerHTML = `<option value="device">This device</option>${extra}`;
}

// --- Points -----------------------------------------------------------------
const OUTSIDE_MSG = "That point is outside the mapped area (the shaded part of the map). "
  + "Pick somewhere inside the dashed box, or build a bigger region.";

function currentPoint(which) {
  return { start: state.start, end: state.end, loop: state.loopStart }[which];
}

function setPoint(which, latlon, label) {
  if (latlon && !rmap.inRegion(latlon)) {
    setStatus(OUTSIDE_MSG, true);
    const prev = currentPoint(which);  // put a dragged pin back where it was
    if (prev) setPoint(which, prev, $({ start: "#start-input", end: "#end-input", loop: "#loop-input" }[which]).value);
    return false;
  }
  if (which === "start") state.start = latlon;
  if (which === "end") state.end = latlon;
  if (which === "loop") state.loopStart = latlon;
  const input = { start: "#start-input", end: "#end-input", loop: "#loop-input" }[which];
  $(input).value = latlon ? (label || fmt(latlon)) : "";
  const pin = { start: ["A", "#1a7f37"], end: ["B", "#222"], loop: ["S", "#1a7f37"] }[which];
  rmap.setPin(which, latlon, pin[0], pin[1], (p) => setPoint(which, p));
  return true;
}

function onMapClick(latlon) {
  if (state.tab === "loop") return setPoint("loop", latlon);
  if (state.tab !== "ab") return;
  if (!rmap.inRegion(latlon)) { setStatus(OUTSIDE_MSG, true); return; }
  setStatus("");
  if (!state.start || (state.start && state.end)) {
    if (state.start && state.end) setPoint("end", null);
    setPoint("start", latlon);
  } else {
    setPoint("end", latlon);
    findAlternatives();
  }
}

// --- Place search (debounced, Nominatim via backend) ------------------------
function attachSearch(inputSel, which) {
  const input = $(inputSel);
  const box = document.createElement("div");
  box.className = "suggestions hidden";
  input.parentElement.appendChild(box);
  let timer;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 3 || /^-?\d+\.\d+,/.test(q)) { box.classList.add("hidden"); return; }
    timer = setTimeout(async () => {
      const results = await api(`/api/geocode?q=${encodeURIComponent(q)}`).catch(() => []);
      box.innerHTML = results.map((r, i) => `<div data-i="${i}">${r.address}</div>`).join("")
        || "<div>No matches inside the mapped area</div>";
      box.classList.remove("hidden");
      box.querySelectorAll("[data-i]").forEach((el) => el.addEventListener("click", () => {
        const r = results[+el.dataset.i];
        setPoint(which, [r.latitude, r.longitude], r.address.split(",").slice(0, 2).join(","));
        box.classList.add("hidden");
        rmap.map.panTo([r.latitude, r.longitude]);
      }));
    }, 450);
  });
  input.addEventListener("blur", () => setTimeout(() => box.classList.add("hidden"), 200));
}

// --- Actions -----------------------------------------------------------------
function needPoints() {
  if (!state.start || !state.end) { setStatus("Set a start and an end (tap the map or search)", true); return false; }
  return true;
}

function findAlternatives() {
  if (!needPoints()) return;
  run("Generating and rating routes…", () =>
    api(`/api/alternatives?start=${fmt(state.start)}&end=${fmt(state.end)}`));
}

function customRoute() {
  if (!needPoints()) return;
  const params = SLIDERS.map(([k]) => `${k}=${$(`#w-${k}`).value}`).join("&");
  run("Routing with your mix…", async () =>
    [await api(`/api/route?start=${fmt(state.start)}&end=${fmt(state.end)}&profile=custom&${params}`)]
      .map((r) => ({ ...r, title: "Your mix" })));
}

function generateLoops() {
  if (!state.loopStart) { setStatus("Choose a start point (tap the map or search)", true); return; }
  const km = $("#loop-km").value, profile = $("#loop-profile").value;
  run(`Generating ${km} km loops…`, () =>
    api(`/api/loop?start=${fmt(state.loopStart)}&km=${km}&profile=${profile}&count=3`));
}

function switchTab(tab, load = true) {
  state.tab = tab;
  rmap.showTrack(null);
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("hidden", b.dataset.body !== tab));
  ["start", "end", "loop"].forEach((w) => setPoint(w, null));
  showResults([]);
  setStatus("");
  if (tab === "rides" && load) loadRides().catch((err) => setStatus(err.message, true));
  if (tab === "suggested") {
    run("Loading suggested rides…", async () => {
      const rides = await api("/api/suggested");
      if (!rides.length) throw new Error("No suggested rides yet - run: cycleroutes catalog");
      return rides.sort((a, b) => b.stats.ratings.overall - a.stats.ratings.overall);
    });
  }
}

// --- Setup -------------------------------------------------------------------
function buildControls() {
  $("#ab-sliders").innerHTML = SLIDERS.map(([k, label, v]) =>
    `<label for="w-${k}">${label}</label><input id="w-${k}" type="range" min="0" max="5" step="0.5" value="${v}">
     <output id="o-${k}">${v}</output>`).join("");
  SLIDERS.forEach(([k]) => $(`#w-${k}`).addEventListener("input", (e) => { $(`#o-${k}`).textContent = e.target.value; }));

  $("#loop-profile").innerHTML = Object.entries(region.profiles)
    .map(([k, p]) => `<option value="${k}" ${k === "scenic" ? "selected" : ""}>${p.label} — ${p.description}</option>`).join("");
  $("#loop-km").addEventListener("input", (e) => { $("#loop-km-val").textContent = e.target.value; });

  $("#legend").innerHTML = Object.entries(region.lts_labels)
    .map(([k, label]) => `<i style="background:${region.lts_colors[k]}"></i><span>${label}</span>`).join("");

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("#ab-go").addEventListener("click", findAlternatives);
  $("#custom-go").addEventListener("click", customRoute);
  $("#loop-go").addEventListener("click", generateLoops);
  $("#stress-toggle").addEventListener("change", (e) => rmap.toggleStress(e.target.checked));
  $("#amenity-toggle").addEventListener("change", async (e) => {
    const n = await rmap.toggleAmenities(e.target.checked);
    if (e.target.checked && !n) setStatus("No amenities for this region yet - run: cycleroutes amenities", true);
  });
  $("#gps-source").addEventListener("change", async (e) => {
    rider.source = e.target.value;
    if (e.target.value !== "device") await post(`/api/gps/sources/${e.target.value}/activate`, {});
  });
  $("#record-go").addEventListener("click", () => {
    $("#panel").classList.add("collapsed");
    rider.start(null).catch((err) => setStatus(err.message, true));
  });
  $("#panel-handle").addEventListener("click", () => {
    const panel = $("#panel");
    panel.scrollTop = 0;
    panel.classList.toggle("collapsed");
  });
  document.querySelectorAll("[data-locate]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const p = await rmap.locate();
      if (setPoint(b.dataset.locate, p, "My location")) rmap.map.panTo(p);
    } catch (err) { setStatus(`Couldn't get your location: ${err.message}`, true); }
  }));
  attachSearch("#start-input", "start");
  attachSearch("#end-input", "end");
  attachSearch("#loop-input", "loop");
}

async function init() {
  try {
    region = await api("/api/region");
  } catch (err) {
    setStatus(`Backend not ready: ${err.message}`, true);
    return;
  }
  rmap = new RouteMap("map", region, onMapClick);
  rider = new RideController({ api, post, rmap, setStatus, onFinished: onRideFinished,
    onReroute: (route) => { state.routes = [route]; state.selected = route.id; refresh(false); } });
  buildControls();
  loadGpsSources();
  window.cycleRoutes = { map: rmap.map, state, rider };  // debugging / automated UI checks
  setStatus("Tap the map to set a start, then an end.");
}

init();
