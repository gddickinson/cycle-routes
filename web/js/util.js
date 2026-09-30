// Small helpers shared by all modules.

export const $ = (sel) => document.querySelector(sel);
export const fmt = (p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`;
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function handle(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

export const api = (path) => fetch(path).then(handle);
export const post = (path, body = {}) => fetch(path, { method: "POST",
  headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(handle);
export const del = (path) => fetch(path, { method: "DELETE" }).then(handle);

// localStorage can be unavailable (private mode); never let that break the app.
export function remember(key, value) {
  try { localStorage.setItem(`cr.${key}`, JSON.stringify(value)); } catch { /* ignore */ }
}
export function recall(key, fallback) {
  try { const v = localStorage.getItem(`cr.${key}`); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}
