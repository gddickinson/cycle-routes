// Leaflet map: basemaps, stress layer, route drawing and start/end pins.

const L = window.L;
const AMENITY_EMOJI = { bike_shop: "🔧", repair: "🛠", water: "💧", toilets: "🚻", bike_share: "🚲", parking: "🅿" };
const AMENITY_MIN_ZOOM = { bike_shop: 12, repair: 12, bike_share: 13, water: 14, toilets: 14, parking: 16 };

export class RouteMap {
  constructor(el, region, onClick) {
    this.region = region;
    this.map = L.map(el, { zoomControl: false }).setView(region.center, 14);
    L.control.zoom({ position: "topright" }).addTo(this.map);
    const cyclosm = L.tileLayer("https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png", {
      maxZoom: 20, attribution: '<a href="https://www.cyclosm.org">CyclOSM</a> | © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    });
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap contributors",
    });
    cyclosm.addTo(this.map);
    L.control.layers({ "Cycle map (CyclOSM)": cyclosm, "OpenStreetMap": osm }, null,
      { position: "topright" }).addTo(this.map);
    const [s, w, n, e] = region.bbox;
    this.bounds = L.latLngBounds([[s, w], [n, e]]);
    // Grey out everything outside the mapped area (a world-sized polygon with the region as a hole).
    L.polygon([[[-85, -180], [85, -180], [85, 180], [-85, 180]], [[s, w], [n, w], [n, e], [s, e]]], {
      stroke: false, fillColor: "#333", fillOpacity: 0.35, interactive: false,
    }).addTo(this.map);
    L.rectangle(this.bounds, { color: "#333", weight: 2, fill: false, dashArray: "6 6",
      interactive: false }).addTo(this.map);
    this.map.fitBounds(this.bounds, { paddingTopLeft: window.innerWidth > 700 ? [400, 10] : [10, 10] });
    this.renderer = L.canvas({ padding: 0.5 });
    this.routeLayer = L.layerGroup().addTo(this.map);
    this.pins = {};
    this.map.on("click", (ev) => onClick([ev.latlng.lat, ev.latlng.lng]));
  }

  color(lts) { return this.region.lts_colors[lts]; }

  inRegion(latlon) { return this.bounds.contains(latlon); }

  setPin(name, latlon, label, color, onMove) {
    if (this.pins[name]) this.pins[name].remove();
    if (!latlon) { delete this.pins[name]; return; }
    const icon = L.divIcon({ className: "", iconSize: [26, 26],
      html: `<div class="pin" style="background:${color}">${label}</div>` });
    const m = L.marker(latlon, { icon, draggable: true }).addTo(this.map);
    m.on("dragend", () => { const p = m.getLatLng(); onMove([p.lat, p.lng]); });
    this.pins[name] = m;
  }

  clearPins() { Object.keys(this.pins).forEach((k) => this.setPin(k, null)); }

  async toggleStress(on) {
    if (!on) { if (this.stress) this.stress.remove(); return; }
    if (!this.stressData) {
      const res = await fetch("/api/network");
      this.stressData = await res.json();
    }
    this.stress = L.geoJSON(this.stressData, {
      renderer: this.renderer, interactive: false,
      style: (f) => ({ color: this.color(f.properties.lts), weight: f.properties.route ? 3 : 2,
        opacity: 0.8 }),
    }).addTo(this.map);
    this.stress.bringToBack();
  }

  // Draw all routes faintly and the selected one on top, coloured by stress.
  showRoutes(routes, selectedId, onSelect, maxOthers = 8) {
    this.routeLayer.clearLayers();
    let selectedBounds = null;
    for (const r of routes.length <= maxOthers ? routes : []) {
      const selected = r.id === selectedId;
      if (!selected) {
        L.geoJSON(r.geojson, { renderer: this.renderer,
          style: { color: "#4a5a70", weight: 5, opacity: 0.45 } })
          .on("click", (ev) => { L.DomEvent.stop(ev); onSelect(r.id); })
          .addTo(this.routeLayer);
      }
    }
    const sel = routes.find((r) => r.id === selectedId);
    if (sel) {
      const halo = L.geoJSON(sel.geojson, { renderer: this.renderer, interactive: false,
        style: { color: "#fff", weight: 9, opacity: 0.95 } }).addTo(this.routeLayer);
      L.geoJSON(sel.geojson, { renderer: this.renderer,
        style: (f) => ({ color: this.color(f.properties.lts), weight: 5.5, opacity: 1 }),
        onEachFeature: (f, layer) => {
          const n = f.properties.name ? `${f.properties.name}<br>` : "";
          layer.bindTooltip(`${n}Stress LTS ${f.properties.lts} · safety ${Math.round(f.properties.safety * 10)}/10`,
            { sticky: true });
        } }).addTo(this.routeLayer);
      selectedBounds = halo.getBounds();
    }
    return selectedBounds;
  }

  fit(bounds) {
    if (!bounds) return;
    const phone = window.innerWidth <= 700;
    this.map.fitBounds(bounds, phone
      ? { paddingTopLeft: [20, 20], paddingBottomRight: [20, window.innerHeight * 0.55 + 10] }
      : { paddingTopLeft: [410, 30], paddingBottomRight: [30, 30] });
  }

  // --- Live position, recorded tracks, amenities ------------------------------
  showPosition(fix, follow = true) {
    const ll = [fix.latitude, fix.longitude];
    if (!this.posMarker) {
      this.accCircle = L.circle(ll, { radius: 1, color: "#1f6feb", weight: 1, fillOpacity: 0.12,
        interactive: false }).addTo(this.map);
      this.posMarker = L.circleMarker(ll, { radius: 8, color: "#fff", weight: 3, fillColor: "#1f6feb",
        fillOpacity: 1, interactive: false }).addTo(this.map);
    }
    this.posMarker.setLatLng(ll);
    this.accCircle.setLatLng(ll).setRadius(Math.min(fix.accuracy_m || 0, 500));
    if (follow) this.map.panTo(ll, { animate: true });
  }

  clearPosition() {
    if (this.posMarker) { this.posMarker.remove(); this.accCircle.remove(); }
    this.posMarker = this.accCircle = null;
  }

  showTrack(geojson) {
    if (this.track) this.track.remove();
    this.track = null;
    if (!geojson) return null;
    this.track = L.geoJSON(geojson, { interactive: false,
      style: { color: "#1f6feb", weight: 3, opacity: 0.9, dashArray: "2 6" } }).addTo(this.map);
    return this.track.getBounds();
  }

  // Amenities appear by zoom so the map never drowns in pins (hundreds of bike racks downtown).
  async toggleAmenities(on) {
    if (this.amenities) { this.amenities.remove(); this.amenities = null; }
    if (this._amenityZoom) { this.map.off("zoomend", this._amenityZoom); this._amenityZoom = null; }
    if (!on) return 0;
    if (!this.amenityData) this.amenityData = await (await fetch("/api/amenities")).json();
    const draw = () => {
      if (this.amenities) this.amenities.remove();
      const z = this.map.getZoom();
      this.amenities = L.geoJSON(this.amenityData, {
        filter: (f) => z >= (AMENITY_MIN_ZOOM[f.properties.category] ?? 14),
        pointToLayer: (f, ll) => L.marker(ll, { icon: L.divIcon({ className: "", iconSize: [24, 24],
          html: `<div class="poi poi-${f.properties.category}">${AMENITY_EMOJI[f.properties.category] || "•"}</div>` }) }),
        onEachFeature: (f, layer) => {
          const p = f.properties;
          const bits = [p.name, p.opening_hours, p.capacity && `${p.capacity} spaces`, p.fee === "yes" && "fee"]
            .filter(Boolean).map((t) => String(t).replace(/</g, "&lt;"));
          layer.bindPopup(`<b>${p.label}</b>${bits.length ? "<br>" + bits.join("<br>") : ""}`);
        },
      }).addTo(this.map);
    };
    this._amenityZoom = draw;
    this.map.on("zoomend", draw);
    draw();
    return this.amenityData.features.length;
  }

  locate() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error("Location not available"));
      navigator.geolocation.getCurrentPosition(
        (p) => resolve([p.coords.latitude, p.coords.longitude]),
        (err) => reject(err), { enableHighAccuracy: true, timeout: 10000 });
    });
  }
}
