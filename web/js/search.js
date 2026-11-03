// Place search (Nominatim via the backend, limited to the mapped area).
// Searches only when the user presses Enter: Nominatim's usage policy forbids
// search-as-you-type (autocomplete) against its public servers.

import { $, api, esc } from "./util.js";

export function attachSearch(inputSel, onPick) {
  const input = $(inputSel);
  const box = document.createElement("div");
  box.className = "suggestions hidden";
  input.parentElement.appendChild(box);
  input.addEventListener("input", () => box.classList.add("hidden"));
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") { box.classList.add("hidden"); return; }
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = input.value.trim();
    if (q.length < 3 || /^-?\d+\.\d+,/.test(q)) { box.classList.add("hidden"); return; }
    box.innerHTML = "<div>Searching…</div>";
    box.classList.remove("hidden");
    const results = await api(`/api/geocode?q=${encodeURIComponent(q)}`).catch(() => []);
    box.innerHTML = results.map((r, i) => `<div data-i="${i}">${esc(r.address)}</div>`).join("")
      || "<div>No matches inside the mapped area</div>";
    box.querySelectorAll("[data-i]").forEach((el) => el.addEventListener("click", () => {
      const r = results[+el.dataset.i];
      onPick([r.latitude, r.longitude], r.address.split(",").slice(0, 2).join(","));
      box.classList.add("hidden");
    }));
  });
  input.addEventListener("blur", () => setTimeout(() => box.classList.add("hidden"), 200));
}
