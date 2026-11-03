// Safety notice: shown on first launch (and again whenever its wording changes), and on
// demand from the "safety notice" links. Routes are generated automatically, never checked
// by a person, so riders and walkers must not rely on them for their safety.

import { $, recall, remember } from "./util.js";

const VERSION = 1;          // bump when the wording changes so everyone sees it again

export function showSafetyNotice() {
  $("#safety").classList.remove("hidden");
  $("#safety-ok").focus();
}

export function initSafetyNotice() {
  $("#safety-ok").addEventListener("click", () => {
    remember("safetyAck", VERSION);
    $("#safety").classList.add("hidden");
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-safety]")) { e.preventDefault(); showSafetyNotice(); }
  });
  if (recall("safetyAck", 0) < VERSION) showSafetyNotice();
}
