// Canvas map of the demo street network (no tile server: the OpenStreetMap streets themselves are drawn, coloured
// by traffic stress). Drag or arrow keys to pan, wheel / pinch / +/- to zoom, click or Enter to pick a point.
import { esc } from './core.js';

export class MapView {
  constructor(host, eng, { onPick = null, height = 560 } = {}) {
    this.eng = eng; this.onPick = onPick; this.routes = []; this.markers = []; this.dim = false;
    const a = eng.demo.area;
    this.lat0 = a.lat; this.lon0 = a.lon; this.kx = Math.cos(a.lat * Math.PI / 180);
    host.innerHTML = `<div class="mapwrap stage">
      <canvas tabindex="0" role="application" aria-label="Street map of ${esc(a.title)}: drag or use arrow keys to pan, + and - to zoom, click or press Enter to pick the point at the centre"></canvas>
      <div class="mapbtns"><button type="button" class="alt" data-z="1" aria-label="Zoom in">+</button><button type="button" class="alt" data-z="-1" aria-label="Zoom out">−</button><button type="button" class="alt" data-z="0" aria-label="Reset view">⟲</button></div>
      <div class="cross" aria-hidden="true"></div>
      <div class="attrib">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (ODbL)</div>
    </div>`;
    this.canvas = host.querySelector('canvas');
    this.canvas.style.height = height + 'px';
    this.ctx = this.canvas.getContext('2d');
    host.querySelectorAll('[data-z]').forEach(b => b.addEventListener('click', () => {
      const z = +b.dataset.z; if (z === 0) this.reset(); else this.zoomAt(z > 0 ? 1.5 : 1 / 1.5);
    }));
    this.bind();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.canvas);
    this.resize();
  }

  // --- projection ---------------------------------------------------------------------------
  px([lon, lat]) { return [this.w / 2 + ((lon - this.cx) * this.kx) * this.s, this.h / 2 - (lat - this.cy) * this.s]; }
  unpx(x, y) { return [this.cy - (y - this.h / 2) / this.s, this.cx + (x - this.w / 2) / this.s / this.kx]; }

  reset() {
    const [s, w, n, e] = this.eng.demo.area.bbox;
    this.cx = (w + e) / 2; this.cy = (s + n) / 2;
    this.s = Math.min(this.w / ((e - w) * this.kx), this.h / (n - s)) * 0.96;
    this.minS = this.s * 0.6;
    this.redraw();
  }

  resize() {
    const r = this.canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    if (!r.width) return;
    const first = !this.w;
    this.w = r.width; this.h = r.height;
    this.canvas.width = Math.round(r.width * dpr); this.canvas.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (first) this.reset(); else this.redraw();
  }

  zoomAt(f, x = this.w / 2, y = this.h / 2) {
    const [lat, lon] = this.unpx(x, y);
    this.s = Math.min(Math.max(this.s * f, this.minS), this.minS * 60);
    const [lat2, lon2] = this.unpx(x, y);
    this.cx += lon - lon2; this.cy += lat - lat2;
    this.redraw();
  }

  pan(dx, dy) { this.cx -= dx / this.s / this.kx; this.cy += dy / this.s; this.redraw(); }

  bind() {
    const c = this.canvas, pts = new Map();
    let moved = 0, pinch = 0;
    c.addEventListener('pointerdown', e => { c.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.offsetX, e.offsetY]); moved = 0; });
    c.addEventListener('pointermove', e => {
      if (!pts.has(e.pointerId)) return;
      const [px, py] = pts.get(e.pointerId);
      if (pts.size === 2) {
        const other = [...pts.entries()].find(([id]) => id !== e.pointerId)[1];
        const d0 = Math.hypot(px - other[0], py - other[1]), d1 = Math.hypot(e.offsetX - other[0], e.offsetY - other[1]);
        if (d0 > 0) this.zoomAt(d1 / d0, (e.offsetX + other[0]) / 2, (e.offsetY + other[1]) / 2);
        pinch = 1;
      } else {
        this.pan(e.offsetX - px, e.offsetY - py);
      }
      moved += Math.abs(e.offsetX - px) + Math.abs(e.offsetY - py);
      pts.set(e.pointerId, [e.offsetX, e.offsetY]);
    });
    const up = e => {
      if (!pts.has(e.pointerId)) return;
      pts.delete(e.pointerId);
      if (!pts.size) { if (moved < 6 && !pinch && this.onPick) this.onPick(...this.unpx(e.offsetX, e.offsetY)); pinch = 0; }
    };
    c.addEventListener('pointerup', up);
    c.addEventListener('pointercancel', e => { pts.delete(e.pointerId); pinch = 0; });
    c.addEventListener('wheel', e => { e.preventDefault(); this.zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.offsetX, e.offsetY); }, { passive: false });
    c.addEventListener('keydown', e => {
      const step = 60, k = e.key;
      if (k === 'ArrowLeft') this.pan(step, 0); else if (k === 'ArrowRight') this.pan(-step, 0);
      else if (k === 'ArrowUp') this.pan(0, step); else if (k === 'ArrowDown') this.pan(0, -step);
      else if (k === '+' || k === '=') this.zoomAt(1.5); else if (k === '-') this.zoomAt(1 / 1.5);
      else if (k === 'Enter' && this.onPick) this.onPick(this.cy, this.cx);
      else return;
      e.preventDefault();
    });
  }

  // --- drawing ----------------------------------------------------------------------------------
  setRoutes(routes) { this.routes = routes; this.redraw(); }
  setMarkers(markers) { this.markers = markers; this.redraw(); }
  fit(coords) {
    if (!coords.length) return;
    const xs = coords.map(p => p[0]), ys = coords.map(p => p[1]);
    const w = Math.min(...xs), e = Math.max(...xs), s = Math.min(...ys), n = Math.max(...ys);
    this.cx = (w + e) / 2; this.cy = (s + n) / 2;
    this.s = Math.max(Math.min(this.w / (((e - w) || 1e-4) * this.kx), this.h / ((n - s) || 1e-4)) * 0.8, this.minS);
    this.redraw();
  }

  redraw() {
    if (this.raf || !this.w) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.draw(); });
  }

  line(coords) {
    const g = this.ctx;
    g.beginPath();
    coords.forEach((p, i) => { const [x, y] = this.px(p); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
    g.stroke();
  }

  draw() {
    const g = this.ctx, colors = this.eng.model.lts_colors;
    g.fillStyle = '#05070d'; g.fillRect(0, 0, this.w, this.h);
    g.lineCap = 'round'; g.lineJoin = 'round';
    const zoom = this.s / this.minS;
    g.globalAlpha = this.routes.length || this.dim ? 0.45 : 0.9;
    g.lineWidth = Math.min(1 + zoom * 0.35, 4);
    for (const e of this.eng.draw) { g.strokeStyle = colors[e.lts]; this.line(e.geometry); }
    g.globalAlpha = 1;
    for (const r of this.routes.filter(r => !r.selected).concat(this.routes.filter(r => r.selected))) {
      g.setLineDash(r.dashed ? [8, 6] : []);
      g.strokeStyle = 'rgba(0,0,0,.75)'; g.lineWidth = (r.selected ? 9 : 6); this.line(r.coords);
      g.strokeStyle = r.color; g.lineWidth = r.selected ? 5 : 3; g.globalAlpha = r.selected ? 1 : 0.7;
      g.shadowColor = r.color; g.shadowBlur = r.selected ? 10 : 0;
      this.line(r.coords);
      g.shadowBlur = 0; g.globalAlpha = 1;
    }
    g.setLineDash([]);
    for (const m of this.markers) {
      const [x, y] = this.px([m.lon, m.lat]);
      g.fillStyle = m.color || '#fff'; g.strokeStyle = '#000'; g.lineWidth = 2;
      g.beginPath(); g.arc(x, y, 11, 0, 2 * Math.PI); g.fill(); g.stroke();
      g.fillStyle = '#000'; g.font = '700 12px ui-monospace, Menlo, monospace'; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(m.label, x, y + 0.5);
    }
  }

  destroy() { this.ro.disconnect(); }
}
