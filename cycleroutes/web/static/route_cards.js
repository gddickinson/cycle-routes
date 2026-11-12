// Rated route cards, LTS share bar, cue sheet and elevation profile (shared by the planner and the examples page).
import { esc, list } from './core.js';

export const ROUTE_COLORS = ['#4fd2ff', '#ff6fd8', '#ffd23f', '#b18cff', '#ff8a3d', '#7cffcb', '#ff5c7a', '#c8f560', '#ffffff', '#5f9dff'];
const RATING_LABELS = { overall: 'Overall', safety: 'Safety', fun: 'Fun', traffic: 'Quiet', hills: 'Hills', speed: 'Speed', surface: 'Surface', shade: 'Shade' };

export function ltsBar(pct, colors) {
  return `<div class="ltsbar" role="img" aria-label="Traffic stress along the route: ${[1, 2, 3, 4].map(k => `LTS ${k} ${pct[k]}%`).join(', ')}">
    ${[1, 2, 3, 4].map(k => pct[k] > 0 ? `<span style="width:${pct[k]}%;background:${colors[k]}"></span>` : '').join('')}</div>`;
}

function ratingRows(r) {
  return Object.keys(RATING_LABELS).filter(k => r[k] !== undefined).map(k => `
    <div class="rate${k === 'overall' ? ' all' : ''}"><span>${RATING_LABELS[k]}</span>
      <i><b style="width:${r[k] * 10}%"></b></i><em>${r[k].toFixed(1)}</em></div>`).join('');
}

export function routeCard(r, i, colors, { selected = false, badge = '' } = {}) {
  const s = r.stats, c = ROUTE_COLORS[i % ROUTE_COLORS.length];
  const title = r.title || r.profile_label;
  return `<div class="card click rcard${selected ? ' sel' : ''}" data-i="${i}" tabindex="0" role="button" aria-pressed="${selected}" style="--rc:${c}">
    <div class="rhead"><span class="swatch" style="background:${c}"></span><b>${esc(title)}</b>${badge}</div>
    ${r.also_best_for && r.also_best_for.length ? `<small>also best for: ${esc(r.also_best_for.join(', '))}</small>` : ''}
    <div class="facts"><span><b>${s.distance_km.toFixed(2)}</b> km</span><span><b>${Math.round(s.duration_min)}</b> min</span>
      <span><b>${s.ascent_m}</b> m up</span><span>${esc(s.hill_label)}</span></div>
    ${ltsBar(s.lts_pct, colors)}
    <div class="rates">${ratingRows(s.ratings)}</div>
    <div class="small mute">${s.bike_infra_pct}% bike lanes/paths · ${s.trail_pct}% trails · ${s.risky_crossings} risky crossing${s.risky_crossings === 1 ? '' : 's'}${s.avoided_km ? ` · ${s.avoided_km} km on avoided roads` : ''}${s.distance_error_pct !== undefined ? ` · ${s.distance_error_pct}% off target, ${s.reuse_pct}% re-ridden` : ''}</div>
    ${s.notice ? `<p class="warnc small">${esc(s.notice)}</p>` : ''}
  </div>`;
}

export function bindCards(host, onSelect) {
  host.querySelectorAll('.rcard').forEach(el => {
    const pick = () => onSelect(+el.dataset.i);
    el.addEventListener('click', pick);
    el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
  });
}

export function cueList(cues, colors) {
  return `<ol class="cues">${list(cues, c => `<li><span class="km">${c.at_km.toFixed(2)} km</span>
    <span class="dot" style="background:${colors[c.lts]}" title="LTS ${c.lts}"></span>${esc(c.instruction)}</li>`)}</ol>`;
}

// Elevation profile [[km, m], ...] as a small inline SVG.
export function elevationSvg(profile) {
  if (!profile || profile.length < 2) return '';
  const W = 600, H = 120, xs = profile.map(p => p[0]), zs = profile.map(p => p[1]);
  const x0 = xs[0], x1 = xs[xs.length - 1] || 1, z0 = Math.min(...zs), z1 = Math.max(...zs), dz = Math.max(z1 - z0, 5);
  const pt = ([x, z]) => `${(((x - x0) / ((x1 - x0) || 1)) * W).toFixed(1)},${(H - 8 - ((z - z0) / dz) * (H - 24)).toFixed(1)}`;
  const d = profile.map(pt).join(' ');
  return `<svg class="elev" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
    aria-label="Elevation profile: ${Math.round(z0)} to ${Math.round(z1)} m over ${x1.toFixed(1)} km">
    <polygon points="0,${H} ${d} ${W},${H}" class="fill"/><polyline points="${d}" class="ln"/>
    <text x="4" y="14">${Math.round(z1)} m</text><text x="4" y="${H - 4}">${Math.round(z0)} m</text>
    <text x="${W - 4}" y="${H - 4}" text-anchor="end">${x1.toFixed(1)} km</text></svg>`;
}

export function safetyNote(model) {
  return `<p class="callout small" role="note"><b>Safety:</b> ${esc(model.safety_notice)}</p>`;
}
