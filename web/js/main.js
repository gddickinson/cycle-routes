// App wiring: tabs, points, planning requests, results, rides; delegates to modules.

import { renderCards } from "./cards.js";
import { Layers } from "./layers.js";
import { RouteMap } from "./map.js";
import { More } from "./more.js";
import { Plan } from "./plan.js";
import { RideController } from "./ride.js";
import { renderRides, summaryHtml } from "./rides.js";
import { attachSearch } from "./search.js";
import { initSafetyNotice } from "./notice.js";
import { TripBuilder } from "./trip.js";
import { Voice } from "./voice.js";
import { Settings, planLink, readLink } from "./settings.js";
import { $, api, copyText, del, esc, fmt, post, recall, remember } from "./util.js";

const SLIDERS = [["safety", "Safety", 3], ["fun", "Fun", 1], ["traffic", "Low traffic", 1],
  ["hills", "Avoid hills", 1], ["surface", "Smooth", 0.5], ["shade", "Shade", 0.5]];
const OUTSIDE_MSG = "That point is outside the mapped area (the shaded part of the map). "
  + "Pick somewhere inside the dashed box, or build a bigger area under More.";
const INPUTS = { start: "#start-input", end: "#end-input", loop: "#loop-input" };

const state = { tab: "ab", start: null, end: null, loopStart: null, routes: [], selected: null,
  mode: recall("mode", "bike") };
const app = { state, api, post, setStatus };
let region, rmap, rider, settings, plan, trips;

function setStatus(text, error = false) {
  const el = $("#status");
  el.textContent = text;
  el.classList.toggle("error", error);
}

// --- Results ---------------------------------------------------------------------------
function showResults(routes) {
  state.routes = routes;
  state.selected = routes.length ? routes[0].id : null;
  refresh(true);
}

function refresh(fit = false) {
  const bounds = rmap.showRoutes(state.routes, state.selected, select);
  renderCards($("#results"), state.routes, state.selected, region.lts_colors, {
    onSelect: select, onRide: rideRoute, onDetails: (r) => plan.loadDetails(r),
    onSave: (r) => plan.saveFavourite(r).catch((e) => setStatus(e.message, true)),
    onExtend: (r) => plan.toggleExtend(r),
    onLink: async (r) => {
      if (!r.request?.start && !r.request?.loop) {
        setStatus("Links re-plan from start and end points, which this route doesn't have - use ★ Save to keep it.", true);
        return;
      }
      const url = planLink(r.request || {});
      setStatus(await copyText(url) ? "Link copied - it re-plans this route when opened." : url);
    },
  });
  if (state.routes.length > 1) {
    $("#results").insertAdjacentHTML("afterbegin", `<button id="compare-go" class="btn small secondary">Compare all ${state.routes.length}</button>`);
    $("#compare-go").addEventListener("click", () => {
      $("#compare-go").insertAdjacentHTML("afterend", plan.compareHtml(state.routes));
      $("#compare-go").remove();
    });
  }
  if (fit) rmap.fit(bounds);
}

function select(id) {
  state.selected = id;
  refresh(true);
  $("#panel").classList.remove("collapsed");
}

let requestSeq = 0;   // bumped by every new request and tab switch; stale responses are dropped

async function run(label, fn, request = null) {
  const seq = ++requestSeq;
  setStatus(label);
  $("#results").innerHTML = "";
  try {
    const routes = await fn();
    if (seq !== requestSeq) return;   // superseded (user changed tab or asked for something else)
    routes.forEach((r) => { r.request = { ...(request || {}), profile: request?.profile || r.profile, bike: settings.bike }; });
    const notes = routes[0]?.conditions?.notes?.length ? ` · planned for ${routes[0].conditions.notes.join(", ")}` : "";
    setStatus(routes.length ? `${routes.length} option${routes.length > 1 ? "s" : ""} — tap one for details${notes}` : "Nothing found");
    showResults(routes);
  } catch (err) {
    if (seq === requestSeq) setStatus(err.message, true);
  }
}

// --- Points ----------------------------------------------------------------------------
function setPoint(which, latlon, label) {
  if (latlon && !rmap.inRegion(latlon)) {
    setStatus(OUTSIDE_MSG, true);
    const prev = { start: state.start, end: state.end, loop: state.loopStart }[which];
    if (prev) setPoint(which, prev, $(INPUTS[which]).value);
    return false;
  }
  if (which === "start") state.start = latlon;
  if (which === "end") state.end = latlon;
  if (which === "loop") state.loopStart = latlon;
  $(INPUTS[which]).value = latlon ? (label || fmt(latlon)) : "";
  const pin = { start: ["A", "#1a7f37"], end: ["B", "#222"], loop: ["S", "#1a7f37"] }[which];
  rmap.setPin(which, latlon, pin[0], pin[1], (p) => setPoint(which, p) && state.end && state.tab === "ab" && findAlternatives());
  return true;
}

function onMapClick(latlon) {
  if (!rmap.inRegion(latlon)) { setStatus(OUTSIDE_MSG, true); return; }
  if (state.picking) {                    // another feature asked for a point on the map
    const done = state.picking;
    state.picking = null;
    document.body.classList.remove("picking");
    return done(latlon);
  }
  if (state.tab === "loop") return setPoint("loop", latlon);
  if (state.tab !== "ab") return;
  if (plan.addingVia) return plan.addVia(latlon);
  setStatus("");
  if (!state.start || (state.start && state.end)) {
    if (state.start && state.end) { setPoint("end", null); plan.clearVia(); }
    setPoint("start", latlon);
  } else {
    setPoint("end", latlon);
    findAlternatives();
  }
}

app.pickOnMap = (prompt) => new Promise((resolve) => {
  setStatus(prompt);
  document.body.classList.add("picking");
  if (window.innerWidth <= 700) $("#panel").classList.add("collapsed");
  state.picking = (ll) => { setStatus(""); $("#panel").classList.remove("collapsed"); resolve(ll); };
});
app.addRoute = (route) => {                // a new route derived from another (e.g. extended)
  state.routes = [route, ...state.routes.filter((r) => r.id !== route.id)];
  state.selected = route.id;
  refresh(true);
};
app.settingsQuery = () => settings.query();

app.pointFromMenu = (which, ll, label) => {
  if (state.tab !== "ab") switchTab("ab");
  if (setPoint(which, ll, label) && state.start && state.end) findAlternatives();
};
app.loopFromMenu = (ll) => { switchTab("loop"); setPoint("loop", ll); };

// --- Planning requests -------------------------------------------------------------------
const pointsQuery = () => `start=${fmt(state.start)}&end=${fmt(state.end)}${plan.viaParam()}&${settings.query()}`;
const profilesFor = (mode) => (mode === "walk" ? region.walk_profiles : region.profiles);
const abRequest = (profile) => ({ start: state.start, end: state.end, via: plan.via, profile });

function needPoints() {
  if (!state.start || !state.end) { setStatus("Set a start and an end (tap the map or search)", true); return false; }
  return true;
}

function findAlternatives() {
  if (!needPoints()) return;
  run("Generating and rating routes…", () => api(`/api/alternatives?${pointsQuery()}`), abRequest(null));
}
app.findAlternatives = findAlternatives;

function customRoute() {
  if (!needPoints()) return;
  const params = SLIDERS.map(([k]) => `${k}=${$(`#w-${k}`).value}`).join("&");
  run("Routing with your mix…", async () => [await api(`/api/route?${pointsQuery()}&profile=custom&${params}`)]
    .map((r) => ({ ...r, title: "Your mix" })), abRequest("custom"));
}

function tripAB() {
  if (!needPoints()) return;
  const target = trips.abTargetKm();
  if (!target && !trips.hasStops()) { setStatus("Choose a length and/or some stops first", true); return; }
  run("Planning your trip…", () => post(`/api/trip?${settings.query()}`, {
    start: state.start, end: state.end, target_km: target, stops: trips.stops(),
    profile: state.mode === "walk" ? "balanced" : "scenic" }), abRequest("trip"));
}

function learnedRoute() {
  if (!needPoints()) return;
  run("Routing the way you usually ride…", async () => [await api(`/api/route?${pointsQuery()}&profile=learned`)]
    .map((r) => ({ ...r, title: "Like you usually ride" })), abRequest("learned"));
}

function generateLoops() {
  if (!state.loopStart) { setStatus("Choose a start point (tap the map or search)", true); return; }
  const km = $("#loop-km").value, profile = $("#loop-profile").value;
  if (profile === "tour") {
    const n = $("#tour-stops").value;
    return run(`Planning a ${km} km tour of ${n} sights…`, async () =>
      [await api(`/api/tour?start=${fmt(state.loopStart)}&km=${km}&stops=${n}&${settings.query()}`)],
    { loop: state.loopStart, km, profile });
  }
  if (trips.hasStops()) {
    return run(`Planning ${km} km loops with your stops…`, () => post(`/api/trip?${settings.query()}`,
      { start: state.loopStart, target_km: +km, stops: trips.stops(), profile }), { loop: state.loopStart, km, profile });
  }
  run(`Generating ${km} km loops…`, () =>
    api(`/api/loop?start=${fmt(state.loopStart)}&km=${km}&profile=${profile}&count=3&${settings.query()}`),
  { loop: state.loopStart, km, profile });
}

app.openPlan = (p) => {
  if (p.bike && p.bike !== settings.bike) { $("#bike-type").value = p.bike; settings.bike = p.bike; }
  if (p.loop) {
    switchTab("loop");
    setPoint("loop", p.loop);
    if (p.km) { $("#loop-km").value = p.km; $("#loop-km-val").textContent = p.km; }
    if (p.profile) $("#loop-profile").value = p.profile;
    return generateLoops();
  }
  switchTab("ab");
  setPoint("start", p.start);
  setPoint("end", p.end);
  plan.via = p.via || [];
  plan.renderVia();
  if (p.profile && !["custom", "learned"].includes(p.profile)) {
    run("Re-planning…", async () => [await api(`/api/route?${pointsQuery()}&profile=${p.profile}`)], abRequest(p.profile));
  } else findAlternatives();
};

// --- Riding & rides -----------------------------------------------------------------------
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
  const matched = result.matched ? [result.matched] : [];
  state.routes = matched;
  state.selected = matched[0]?.id || null;
  refresh(true);
  $("#results").insertAdjacentHTML("afterbegin", `<article class="card ride-summary">
    <div class="card-title">Ride saved: ${esc(result.ride.name)}</div>${summaryHtml(result.summary)}</article>`);
  $("#panel").classList.remove("collapsed");
  setStatus("Ride saved. The streets you rode are rated below.");
}

async function loadRides() {
  const rides = await api("/api/rides");
  renderRides($("#results"), rides, {
    onShow: async (id) => {
      const r = await api(`/api/rides/${id}`);
      rmap.showRoutes(r.matched ? [r.matched] : [], r.matched?.id, () => {});
      document.querySelectorAll(".card.ride").forEach((c) => c.classList.toggle("selected", +c.dataset.ride === id));
      rmap.fit(rmap.showTrack(r.track));
      setStatus(`${r.ride.name}: blue dashes = GPS track, colours = streets matched`);
    },
    onDelete: async (id) => { await del(`/api/rides/${id}`); rmap.showTrack(null); loadRides(); },
  });
  setStatus(rides.length ? `${rides.length} recorded ride${rides.length > 1 ? "s" : ""}` : "");
}

async function showHeatmap() {
  const h = await api("/api/rides/heatmap");
  const p = h.properties;
  if (!p.rides) { setStatus("No recorded rides yet.", true); return; }
  rmap.fit(rmap.showTrack(h));
  setStatus(`${p.rides} rides · ${p.ridden_km} km of streets ridden = ${p.coverage_pct}% of the ${p.network_km} km network`);
}

// --- Tabs & controls ------------------------------------------------------------------------
function switchTab(tab, load = true) {
  state.tab = tab;
  requestSeq++;
  rmap.showTrack(null);
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  document.querySelectorAll(".tab-body").forEach((b) => b.classList.toggle("hidden", b.dataset.body !== tab));
  ["start", "end", "loop"].forEach((w) => setPoint(w, null));
  plan.clearVia();
  showResults([]);
  setStatus("");
  if (tab === "rides" && load) loadRides().catch((err) => setStatus(err.message, true));
  if (tab === "more") app.more.load();
  if (tab === "suggested") {
    run("Loading suggested rides…", async () => {
      const rides = await api(`/api/suggested?mode=${state.mode}`);
      if (!rides.length) throw new Error(`No suggested ${state.mode === "walk" ? "walks" : "rides"} yet - run: cycleroutes ${state.mode === "walk" ? "walk" : "catalog"}`);
      return rides.sort((a, b) => b.stats.ratings.overall - a.stats.ratings.overall);
    });
  }
}

function fillLoopProfiles() {
  const profs = profilesFor(state.mode);
  const def = state.mode === "walk" ? "green" : "scenic";
  $("#loop-profile").innerHTML = Object.entries(profs)
    .map(([k, p]) => `<option value="${k}" ${k === def ? "selected" : ""}>${esc(p.label)} — ${esc(p.description)}</option>`).join("")
    + (state.mode === "walk" ? `<option value="tour">Sightseeing tour — visit the best sights nearby</option>` : "");
  $("#tour-field").classList.add("hidden");
}

function setMode(mode) {
  if (mode === "walk" && !region.walk_available) {
    setStatus("Walking routes aren't built for this area yet - run: cycleroutes walk", true);
    return;
  }
  state.mode = mode;
  remember("mode", mode);
  document.body.dataset.mode = mode;
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  document.querySelectorAll(".mode-noun").forEach((el) => { el.textContent = mode === "walk" ? "walk" : "ride"; });
  $("[data-tab=rides]").textContent = mode === "walk" ? "Walks" : "Rides";
  $("#loop-km").max = mode === "walk" ? 25 : 60;
  if (mode === "walk" && +$("#loop-km").value > 10) { $("#loop-km").value = 5; $("#loop-km-val").textContent = 5; }
  fillLoopProfiles();
  settings.setMode(mode);
  trips?.types && trips.render();
  app.layers?.modeChanged();
  switchTab(state.tab === "more" ? "more" : state.tab);
}
app.getMode = () => state.mode;

async function loadGpsSources() {
  const sources = await api("/api/gps/sources").catch(() => []);
  $("#gps-source").innerHTML = `<option value="device">This device</option>` + sources.filter((s) => s.key !== "phone")
    .map((s) => `<option value="${esc(s.key)}">${esc(s.name)}</option>`).join("");
}

function buildControls() {
  $("#ab-sliders").innerHTML = SLIDERS.map(([k, label, v]) =>
    `<label for="w-${k}">${label}</label><input id="w-${k}" type="range" min="0" max="5" step="0.5" value="${v}">
     <output id="o-${k}">${v}</output>`).join("");
  SLIDERS.forEach(([k]) => $(`#w-${k}`).addEventListener("input", (e) => { $(`#o-${k}`).textContent = e.target.value; }));
  fillLoopProfiles();
  $("#tour-stops").addEventListener("input", (e) => { $("#tour-stops-val").textContent = e.target.value; });
  $("#loop-profile").addEventListener("change", () => $("#tour-field").classList.toggle("hidden", $("#loop-profile").value !== "tour"));
  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("#loop-km").addEventListener("input", (e) => { $("#loop-km-val").textContent = e.target.value; });
  $("#legend").innerHTML = Object.entries(region.lts_labels)
    .map(([k, label]) => `<i style="background:${region.lts_colors[k]}"></i><span>${esc(label)}</span>`).join("");

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("#ab-go").addEventListener("click", findAlternatives);
  $("#custom-go").addEventListener("click", customRoute);
  $("#learned-go").addEventListener("click", learnedRoute);
  $("#trip-go").addEventListener("click", tripAB);
  $("#loop-go").addEventListener("click", generateLoops);
  $("#heatmap-go").addEventListener("click", () => showHeatmap().catch((e) => setStatus(e.message, true)));
  $("#gps-source").addEventListener("change", async (e) => {
    rider.source = e.target.value;
    if (e.target.value !== "device") await post(`/api/gps/sources/${e.target.value}/activate`, {});
  });
  $("#record-go").addEventListener("click", () => {
    $("#panel").classList.add("collapsed");
    rider.start(null).catch((err) => setStatus(err.message, true));
  });
  $("#panel-handle").addEventListener("click", () => {
    $("#panel").scrollTop = 0;
    $("#panel").classList.toggle("collapsed");
  });
  document.querySelectorAll("[data-locate]").forEach((b) => b.addEventListener("click", async () => {
    try {
      const p = await rmap.locate();
      if (setPoint(b.dataset.locate, p, "My location")) rmap.map.panTo(p);
    } catch (err) { setStatus(`Couldn't get your location: ${err.message}`, true); }
  }));
  Object.entries(INPUTS).forEach(([which, sel]) => attachSearch(sel, (ll, label) => {
    if (setPoint(which, ll, label)) rmap.map.panTo(ll);
  }));
}

async function init() {
  initSafetyNotice();
  try {
    region = await api("/api/region");
  } catch (err) {
    setStatus(`Backend not ready: ${err.message}`, true);
    return;
  }
  rmap = new RouteMap("map", region, onMapClick);
  Object.assign(app, { region, rmap });
  settings = new Settings(region, () => { if (state.routes.length && state.tab === "ab" && state.end) findAlternatives(); });
  rider = new RideController({ api, post, rmap, setStatus, onFinished: onRideFinished,
    onReroute: (route) => { state.routes = [route]; state.selected = route.id; refresh(false); } });
  rider.settingsQuery = () => settings.query();
  rider.voiceEngine = new Voice();
  plan = new Plan(app);
  Object.assign(app, { settings, plan, rider });
  app.layers = new Layers(app);
  trips = new TripBuilder(app);
  app.more = new More(app);
  buildControls();
  if (state.mode === "walk" && region.walk_available) setMode("walk"); else { state.mode = "bike"; setMode("bike"); }
  loadGpsSources();
  window.cycleRoutes = { map: rmap.map, state, rider, app };  // debugging / automated UI checks
  setStatus("Tap the map to set a start, then an end. Press and hold for more options.");
  const link = readLink();
  if (link) app.openPlan(link);
  navigator.serviceWorker?.register("/sw.js").catch(() => {});   // offline support
}

init();
