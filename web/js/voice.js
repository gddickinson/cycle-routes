// Spoken guidance: choice of voice, speed, pitch, volume, how much is said, and an
// optional chime before each instruction. Settings are remembered on this device.

import { $, esc, recall, remember } from "./util.js";

const DEFAULTS = { voice: "", rate: 1.0, pitch: 1.0, volume: 1.0, detail: "normal", chime: true };
const SAMPLE = "In 200 metres, turn left onto Shoal Creek Trail.";

export class Voice {
  constructor() {
    this.s = { ...DEFAULTS, ...recall("voice-settings", {}) };
    this.voices = [];
    if ("speechSynthesis" in window) {
      this.loadVoices();
      window.speechSynthesis.addEventListener?.("voiceschanged", () => this.loadVoices());
    }
  }

  get available() { return "speechSynthesis" in window; }

  loadVoices() {
    const lang = (navigator.language || "en").slice(0, 2);
    const all = window.speechSynthesis.getVoices();
    // this language first, then everything else; local (offline) voices marked
    this.voices = [...all.filter((v) => v.lang.startsWith(lang)), ...all.filter((v) => !v.lang.startsWith(lang))];
    this.render();
  }

  /** Should a message of this kind be spoken at the current level of detail? */
  wants(kind) {
    const levels = { minimal: ["turn-now", "arrived", "off-route"],
      normal: ["turn-now", "turn-soon", "arrived", "off-route", "start"],
      chatty: ["turn-now", "turn-soon", "arrived", "off-route", "start", "progress"] };
    return (levels[this.s.detail] || levels.normal).includes(kind);
  }

  chime() {
    try {
      const ctx = this.audio || (this.audio = new (window.AudioContext || window.webkitAudioContext)());
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.15 * this.s.volume, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
      o.connect(g).connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + 0.25);
    } catch { /* audio unavailable */ }
  }

  speak(text) {
    if (!this.available) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      const v = this.voices.find((x) => x.voiceURI === this.s.voice);
      if (v) { u.voice = v; u.lang = v.lang; }
      u.rate = this.s.rate;
      u.pitch = this.s.pitch;
      u.volume = this.s.volume;
      if (this.s.chime) this.chime();
      setTimeout(() => window.speechSynthesis.speak(u), this.s.chime ? 280 : 0);
    } catch { /* speech unavailable */ }
  }

  set(changes) {
    Object.assign(this.s, changes);
    remember("voice-settings", this.s);
  }

  render() {
    const box = $("#voice-settings");
    if (!box) return;
    if (!this.available) { box.innerHTML = `<p class="muted">This browser can't speak.</p>`; return; }
    const opts = this.voices.map((v) => `<option value="${esc(v.voiceURI)}" ${v.voiceURI === this.s.voice ? "selected" : ""}>
      ${esc(v.name)} (${esc(v.lang)})${v.localService ? "" : " · online"}</option>`).join("");
    box.innerHTML = `<div class="settings-grid">
      <label for="v-voice">Voice</label><select id="v-voice"><option value="">System default</option>${opts}</select>
      <label for="v-rate">Speed</label><input id="v-rate" type="range" min="0.6" max="1.6" step="0.1" value="${this.s.rate}">
      <label for="v-pitch">Pitch</label><input id="v-pitch" type="range" min="0.6" max="1.5" step="0.1" value="${this.s.pitch}">
      <label for="v-volume">Volume</label><input id="v-volume" type="range" min="0.1" max="1" step="0.1" value="${this.s.volume}">
      <label for="v-detail">Says</label><select id="v-detail">
        <option value="minimal" ${this.s.detail === "minimal" ? "selected" : ""}>Only turns as you reach them</option>
        <option value="normal" ${this.s.detail === "normal" ? "selected" : ""}>Turns ahead and as you reach them</option>
        <option value="chatty" ${this.s.detail === "chatty" ? "selected" : ""}>Everything, plus progress updates</option></select>
      <span></span><label class="toggle"><input type="checkbox" id="v-chime" ${this.s.chime ? "checked" : ""}> Chime before each instruction</label>
    </div><button id="v-test" class="btn small secondary">🔊 Test voice</button>`;
    const bind = (id, key, num) => $(id).addEventListener("change", (e) =>
      this.set({ [key]: num ? +e.target.value : e.target.value }));
    bind("#v-voice", "voice"); bind("#v-rate", "rate", true); bind("#v-pitch", "pitch", true);
    bind("#v-volume", "volume", true); bind("#v-detail", "detail");
    $("#v-chime").addEventListener("change", (e) => this.set({ chime: e.target.checked }));
    $("#v-test").addEventListener("click", () => this.speak(SAMPLE));
  }
}
