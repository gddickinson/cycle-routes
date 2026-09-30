// Live riding: GPS feed (this device or a GPS on the server), recording, turn-by-turn.

const $ = (sel) => document.querySelector(sel);
const FLUSH_MS = 5000;
const POLL_MS = 1000;

export function fmtDist(m) {
  if (m == null) return "";
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.max(0, Math.round(m / 10) * 10)} m`;
}

export function arrowFor(instruction) {
  const t = instruction.toLowerCase();
  const side = t.includes("left") ? "left" : t.includes("right") ? "right" : "";
  if (t.startsWith("sharp")) return side === "left" ? "⤺" : "⤻";
  if (t.startsWith("turn")) return side === "left" ? "↰" : "↱";
  if (t.startsWith("bear")) return side === "left" ? "↖" : "↗";
  if (t.startsWith("arrive")) return "🏁";
  return "↑";
}

export class RideController {
  constructor({ api, post, rmap, setStatus, onFinished, onReroute }) {
    Object.assign(this, { api, post, rmap, setStatus, onFinished, onReroute });
    this.source = "device";
    this.active = false;
    $("#nav-stop").addEventListener("click", () => this.stop());
    $("#nav-reroute").addEventListener("click", () => this.reroute());
  }

  // --- lifecycle ---------------------------------------------------------------
  async start(route = null) {
    if (this.active) await this.stop();
    const ride = await this.post("/api/rides", {
      route_id: route?.id, source: this.source === "device" ? "phone" : this.source,
      name: `${route ? route.title : "Ride"} · ${new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` });
    Object.assign(this, { active: true, rideId: ride.id, route, buffer: [], lastFix: null,
      points: 0, startedAt: Date.now(), restart: true });
    this.showBanner();
    this.renderIdle(route ? "Waiting for GPS…" : "Recording — waiting for GPS…");
    this.flushTimer = setInterval(() => this.flush(), FLUSH_MS);
    this.startFeed();
    this.keepAwake();
  }

  async stop() {
    if (!this.active) return;
    this.active = false;
    this.stopFeed();
    clearInterval(this.flushTimer);
    if (this.wakeLock) this.wakeLock.release().catch(() => {});
    await this.flush();
    $("#nav").classList.add("hidden");
    document.body.classList.remove("navigating");
    this.rmap.clearPosition();
    if (!this.points) {
      this.setStatus("Ride stopped - no GPS positions were received, so nothing was saved.", true);
      await fetch(`/api/rides/${this.rideId}`, { method: "DELETE" });
      return;
    }
    this.setStatus("Saving and rating your ride…");
    const result = await this.post(`/api/rides/${this.rideId}/finish`, {});
    this.onFinished(result);
  }

  // --- position feed -----------------------------------------------------------
  startFeed() {
    if (this.source === "device") {
      if (!navigator.geolocation) { this.renderIdle("This browser has no GPS access."); return; }
      this.watchId = navigator.geolocation.watchPosition(
        (p) => this.onFix({ latitude: p.coords.latitude, longitude: p.coords.longitude,
          accuracy_m: p.coords.accuracy, altitude: p.coords.altitude, heading: p.coords.heading,
          speed_kmh: p.coords.speed != null ? p.coords.speed * 3.6 : null, timestamp: p.timestamp / 1000 }),
        (err) => this.renderIdle(`GPS unavailable: ${err.message}. Phones need https:// or localhost.`),
        { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 });
    } else {
      this.pollTimer = setInterval(async () => {
        const live = await this.api("/api/gps/live").catch(() => null);
        const fix = live?.fix;
        if (fix && (!this.lastFix || fix.timestamp > this.lastFix.timestamp)) this.onFix(fix);
      }, POLL_MS);
    }
  }

  stopFeed() {
    if (this.watchId != null) navigator.geolocation.clearWatch(this.watchId);
    clearInterval(this.pollTimer);
    this.watchId = this.pollTimer = null;
  }

  async onFix(fix) {
    if (!this.active) return;
    this.lastFix = fix;
    this.points += 1;
    this.buffer.push(fix);
    this.rmap.showPosition(fix, true);
    if (!this.route) { this.renderRecording(fix); return; }
    const body = { ...fix, restart: this.restart };
    this.restart = false;
    const nav = await this.post(`/api/navigate/${this.route.id}`, body).catch(() => null);
    if (nav) this.renderNav(nav, fix);
  }

  async flush() {
    if (!this.buffer?.length || this.rideId == null) return;
    const points = this.buffer.splice(0);
    await this.post(`/api/rides/${this.rideId}/points`, { points }).catch(() => this.buffer.unshift(...points));
  }

  async reroute() {
    if (!this.route || !this.lastFix) return;
    const coords = this.route.geojson.features.at(-1).geometry.coordinates.at(-1);
    const profile = this.route.profile in { custom: 1, ridden: 1 } ? "balanced" : this.route.profile;
    $("#nav-warn").textContent = "Finding a new route…";
    try {
      const r = await this.api(`/api/route?start=${this.lastFix.latitude},${this.lastFix.longitude}` +
        `&end=${coords[1]},${coords[0]}&profile=${profile}`);
      this.route = { ...r, title: `${r.title} (rerouted)` };
      this.restart = true;
      this.onReroute(this.route);
      this.onFix(this.lastFix);
    } catch (err) {
      $("#nav-warn").textContent = `Couldn't reroute: ${err.message}`;
    }
  }

  async keepAwake() {
    try { this.wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* optional */ }
  }

  // --- banner ------------------------------------------------------------------
  showBanner() {
    $("#nav").classList.remove("hidden");
    document.body.classList.add("navigating");
    $("#nav-reroute").classList.add("hidden");
    $("#nav-warn").textContent = "";
  }

  renderIdle(text) {
    $("#nav-instr").textContent = text;
    $("#nav-dist").textContent = "";
    $("#nav-meta").textContent = this.route ? this.route.title : "Free ride (no route)";
  }

  renderRecording(fix) {
    const mins = Math.round((Date.now() - this.startedAt) / 60000);
    $("#nav-instr").textContent = "Recording ride";
    $("#nav-dist").textContent = fix.speed_kmh != null ? `${Math.round(fix.speed_kmh)} km/h` : "";
    $("#nav-meta").textContent = `${this.points} GPS points · ${mins} min · ±${Math.round(fix.accuracy_m || 0)} m`;
  }

  renderNav(nav, fix) {
    const cue = nav.next_cue;
    if (nav.off_route) {        // don't show a stale turn instruction while off the route
      $("#nav-arrow").textContent = "⚠";
      $("#nav-dist").textContent = fmtDist(nav.off_route_m);
      $("#nav-instr").textContent = "Off route — head back to the line, or reroute";
    } else {
      $("#nav-instr").textContent = nav.arrived ? "You have arrived 🎉" : cue ? cue.instruction : "Follow the route";
      $("#nav-dist").textContent = nav.arrived ? "" : fmtDist(nav.distance_to_cue_m);
      $("#nav-arrow").textContent = nav.arrived ? "🏁" : arrowFor(cue?.instruction || "");
    }
    const lower1 = (t) => t.charAt(0).toLowerCase() + t.slice(1);   // keep street names' capitals
    const then = nav.then_cue && !nav.arrived && !nav.off_route ? ` · then ${lower1(nav.then_cue.instruction)}` : "";
    $("#nav-meta").textContent = `${fmtDist(nav.remaining_m)} to go · ~${Math.round(nav.remaining_s / 60)} min · ` +
      `${Math.round(nav.fraction * 100)}%${then}`;
    $("#nav-warn").textContent = nav.off_route ? "Off route" :
      (fix.accuracy_m > 60 ? `Weak GPS (±${Math.round(fix.accuracy_m)} m)` : "");
    $("#nav-reroute").classList.toggle("hidden", !nav.off_route);
    $("#nav-stop").textContent = nav.arrived ? "Finish ride" : "Stop";
  }
}
