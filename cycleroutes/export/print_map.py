"""Printable A4 route sheets (PDF): map page + ratings/elevation/cue-sheet page."""

import io
import math
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from cycleroutes import config  # noqa: E402
from cycleroutes.export.tiles import TileManager, choose_zoom, lonlat_to_tile, tile_to_lonlat  # noqa: E402
from cycleroutes.routing.directions import cue_sheet  # noqa: E402
from cycleroutes.routing.geo import haversine_m  # noqa: E402
from cycleroutes.routing.route import Route  # noqa: E402

A4 = (8.27, 11.69)
RATING_ORDER = ["overall", "safety", "fun", "traffic", "hills", "speed", "surface"]
RATING_LABELS = {"overall": "Overall", "safety": "Safety", "fun": "Fun & scenery",
                 "traffic": "Low traffic", "hills": "Easy climbing", "speed": "Speed",
                 "surface": "Surface"}
CUES_PER_PAGE = 34


def _view(lons, lats, aspect: float, pad: float = 0.08):
    """Zoom and tile-space view (x0, y0, x1, y1) around the route, matching the
    map panel's width/height aspect so the whole panel is filled."""
    w, e, s, n = min(lons), max(lons), min(lats), max(lats)
    zoom = choose_zoom(w, s, e, n, max_tiles=24)
    x0, y0 = lonlat_to_tile(w, n, zoom)
    x1, y1 = lonlat_to_tile(e, s, zoom)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_w = max(x1 - x0, 0.2) * (0.5 + pad)
    half_h = max(y1 - y0, 0.2) * (0.5 + pad)
    if half_w / half_h < aspect:
        half_w = half_h * aspect
    else:
        half_h = half_w / aspect
    return zoom, (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def _draw_map(ax, route: Route, tiles: TileManager, aspect: float) -> None:
    coords = route.coords()
    lons, lats = [c[0] for c in coords], [c[1] for c in coords]
    zoom, (vx0, vy0, vx1, vy1) = _view(lons, lats, aspect)
    w, n = tile_to_lonlat(vx0, vy0, zoom)
    e, s = tile_to_lonlat(vx1, vy1, zoom)
    img, (x0, y0, x1, y1) = tiles.stitch(w, s, e, n, zoom)
    ax.imshow(img, extent=(x0, x1, y1, y0), interpolation="lanczos")

    for d in route.edge_data():
        pts = [lonlat_to_tile(x, y, zoom) for x, y in d["geometry"].coords]
        ax.add_collection(LineCollection([pts], colors="white", linewidths=6.5, zorder=3))
        ax.add_collection(LineCollection([pts], colors=config.LTS_COLORS[d["lts"]],
                                         linewidths=4, zorder=4, capstyle="round"))
    _km_markers(ax, route, zoom)
    sx, sy = lonlat_to_tile(lons[0], lats[0], zoom)
    ex, ey = lonlat_to_tile(lons[-1], lats[-1], zoom)
    ax.plot(sx, sy, "o", ms=13, mfc="#1a7f37", mec="white", mew=2, zorder=6)
    ax.text(sx, sy, "S", color="white", ha="center", va="center", fontsize=8, weight="bold", zorder=7)
    if route.kind != "loop":
        ax.plot(ex, ey, "o", ms=13, mfc="#222", mec="white", mew=2, zorder=6)
        ax.text(ex, ey, "F", color="white", ha="center", va="center", fontsize=8, weight="bold", zorder=7)

    ax.set_xlim(vx0, vx1)
    ax.set_ylim(vy1, vy0)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    _scale_bar(ax, zoom, (s + n) / 2, vx0, vy1, vx1 - vx0)
    ax.text(0.995, 0.005, tiles.attribution, transform=ax.transAxes, ha="right", va="bottom",
            fontsize=6, bbox=dict(fc="white", ec="none", alpha=0.8, pad=1.5))
    ax.annotate("N", xy=(0.04, 0.95), xytext=(0.04, 0.87), xycoords="axes fraction",
                ha="center", fontsize=11, weight="bold",
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))


def _km_markers(ax, route: Route, zoom: int) -> None:
    coords = route.coords()
    step = 1 if route.length_m < 15_000 else 2 if route.length_m < 40_000 else 5
    dist, next_km = 0.0, step
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        dist += float(haversine_m(y0, x0, y1, x1))
        if dist >= next_km * 1000:
            tx, ty = lonlat_to_tile(x1, y1, zoom)
            ax.text(tx, ty, str(next_km), fontsize=6.5, ha="center", va="center", zorder=8,
                    bbox=dict(boxstyle="circle,pad=0.25", fc="white", ec="#333", lw=0.8))
            next_km += step


def _scale_bar(ax, zoom, lat, x_left, y_bottom, width_tiles) -> None:

    m_per_tile = 40_075_016.7 * math.cos(math.radians(lat)) / 2 ** zoom
    target = width_tiles * m_per_tile / 5
    nice = min([100, 200, 500, 1000, 2000, 5000, 10000], key=lambda v: abs(v - target))
    length = nice / m_per_tile
    x0, y0 = x_left + 0.04 * width_tiles, y_bottom - 0.05 * width_tiles
    ax.plot([x0, x0 + length], [y0, y0], color="black", lw=3, zorder=9, solid_capstyle="butt")
    label = f"{nice // 1000} km" if nice >= 1000 else f"{nice} m"
    ax.text(x0 + length / 2, y0 - 0.012 * width_tiles, label, ha="center", va="bottom",
            fontsize=8, zorder=9, bbox=dict(fc="white", ec="none", alpha=0.8, pad=1))


def _map_page(pdf, route: Route, stats: dict, title: str, tiles: TileManager) -> None:
    fig = plt.figure(figsize=A4)
    fig.text(0.06, 0.965, title, fontsize=17, weight="bold", va="top")
    summary = (f"{stats['distance_km']} km  ·  ~{stats['duration_min']:.0f} min  ·  "
               f"↑{stats['ascent_m']} m ({stats['hill_label']})  ·  max grade {stats['max_grade_pct']}%  ·  "
               f"overall {stats['ratings']['overall']}/10")
    fig.text(0.06, 0.935, summary, fontsize=10, va="top", color="#333")
    rect = [0.06, 0.1, 0.88, 0.82]
    ax = fig.add_axes(rect)
    _draw_map(ax, route, tiles, aspect=(rect[2] * A4[0]) / (rect[3] * A4[1]))
    handles = [Line2D([], [], color=config.LTS_COLORS[k], lw=4, label=config.LTS_LABELS[k])
               for k in (1, 2, 3, 4)]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.05, 0.015), ncol=2,
               fontsize=8, frameon=False, title="Route colour = traffic stress", title_fontsize=8.5)
    pdf.savefig(fig)
    plt.close(fig)


def _details_page(pdf, route: Route, stats: dict, cues, title: str) -> None:
    fig = plt.figure(figsize=A4)
    fig.text(0.06, 0.965, f"{title} — details", fontsize=14, weight="bold", va="top")

    ax_r = fig.add_axes([0.2, 0.74, 0.3, 0.19])
    vals = [stats["ratings"][k] for k in RATING_ORDER]
    ax_r.barh(range(len(vals)), vals, color=["#333"] + ["#4a7bb7"] * (len(vals) - 1))
    ax_r.set_yticks(range(len(vals)), [RATING_LABELS[k] for k in RATING_ORDER], fontsize=8)
    ax_r.invert_yaxis()
    ax_r.set_xlim(0, 10)
    ax_r.set_title("Ratings (0-10, higher is better)", fontsize=9, loc="left")
    for i, v in enumerate(vals):
        ax_r.text(v + 0.15, i, f"{v}", va="center", fontsize=7.5)
    ax_r.spines[["top", "right"]].set_visible(False)
    ax_r.tick_params(axis="x", labelsize=7)

    facts = [f"Distance: {stats['distance_km']} km", f"Riding time: ~{stats['duration_min']:.0f} min",
             f"Climbing: {stats['ascent_m']} m up / {stats['descent_m']} m down",
             f"On bike infrastructure: {stats['bike_infra_pct']}%",
             f"On signed cycle routes: {stats['signed_route_pct']}%",
             f"Near parks/water: {stats['scenic_pct']}%",
             "Stress mix: " + " / ".join(f"LTS{k} {v:.0f}%" for k, v in stats["lts_pct"].items())]
    if stats.get("signed_routes"):
        facts.append("Routes: " + ", ".join(stats["signed_routes"][:3]))
    fig.text(0.58, 0.93, "\n".join(textwrap.shorten(f, 60) for f in facts), fontsize=8.5,
             va="top", linespacing=1.6)

    prof = route.elevation_profile()
    ax_e = fig.add_axes([0.1, 0.55, 0.84, 0.13])
    xs, zs = [p[0] / 1000 for p in prof], [p[1] for p in prof]
    ax_e.fill_between(xs, zs, min(zs) - 5, color="#b8c9e0")
    ax_e.plot(xs, zs, color="#2f5d8a", lw=1.2)
    ax_e.set_xlim(0, xs[-1] if xs else 1)
    ax_e.set_ylim(min(zs) - 5, max(zs) + 10)
    ax_e.set_xlabel("km", fontsize=8)
    ax_e.set_ylabel("m", fontsize=8)
    ax_e.set_title("Elevation profile", fontsize=9, loc="left")
    ax_e.tick_params(labelsize=7)
    ax_e.spines[["top", "right"]].set_visible(False)

    _cue_table(fig, cues[:CUES_PER_PAGE - 12], top=0.47)
    pdf.savefig(fig)
    plt.close(fig)
    rest = cues[CUES_PER_PAGE - 12:]
    while rest:
        fig = plt.figure(figsize=A4)
        fig.text(0.06, 0.965, f"{title} — directions (cont.)", fontsize=12, weight="bold", va="top")
        _cue_table(fig, rest[:CUES_PER_PAGE * 2], top=0.93)
        pdf.savefig(fig)
        plt.close(fig)
        rest = rest[CUES_PER_PAGE * 2:]


def _cue_table(fig, cues, top: float) -> None:
    fig.text(0.06, top, "Directions", fontsize=10, weight="bold", va="bottom")
    row_h = 0.0245
    for i, cue in enumerate(cues):
        y = top - 0.015 - row_h * (i + 1)
        if y < 0.03:
            break
        fig.patches.append(plt.Rectangle((0.06, y + 0.004), 0.012, 0.012, transform=fig.transFigure,
                                         color=config.LTS_COLORS[cue.lts], figure=fig))
        fig.text(0.08, y + 0.005, f"{cue.at_km:5.2f} km", fontsize=8, family="monospace")
        fig.text(0.19, y + 0.005, textwrap.shorten(cue.instruction, 90), fontsize=8.5)


def route_pdf(route: Route, stats: dict, title: str = "Cycle route",
              basemap: str = "CyclOSM") -> bytes:
    """Render a route to a multi-page A4 PDF and return its bytes."""
    tiles = TileManager(basemap)
    cues = cue_sheet(route)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _map_page(pdf, route, stats, title, tiles)
        _details_page(pdf, route, stats, cues, title)
    return buf.getvalue()
