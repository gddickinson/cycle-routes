"""Extra print layouts: strip maps for long rides and an A6 handlebar cue card."""

import textwrap

import matplotlib.pyplot as plt

from cycleroutes import config
from cycleroutes.routing.geo import haversine_m
from cycleroutes.routing.route import Route

A4 = (8.27, 11.69)
A6 = (4.13, 5.83)
STRIP_KM = 3.0
CUES_PER_CARD = 14


def _cumulative(coords):
    out, d = [0.0], 0.0
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        d += float(haversine_m(y0, x0, y1, x1))
        out.append(d)
    return out


def strip_pages(pdf, route: Route, title: str, tiles, draw_map, segment_km: float = STRIP_KM) -> None:
    """Two close-up maps per A4 page, each covering `segment_km` of the route in order."""
    coords = route.coords()
    cum = _cumulative(coords)
    total = cum[-1] / 1000
    segments = []
    start = 0.0
    while start < total - 0.05:
        end = min(start + segment_km, total)
        seg = [c for c, d in zip(coords, cum) if start * 1000 <= d <= end * 1000]
        if len(seg) >= 2:
            segments.append((start, end, seg))
        start = end
    for i in range(0, len(segments), 2):
        fig = plt.figure(figsize=A4)
        fig.text(0.06, 0.975, f"{title} — strip maps", fontsize=11, weight="bold", va="top")
        for j, (a, b, seg) in enumerate(segments[i:i + 2]):
            rect = [0.06, 0.52 - j * 0.48, 0.88, 0.42]
            ax = fig.add_axes(rect)
            draw_map(ax, route, tiles, aspect=(rect[2] * A4[0]) / (rect[3] * A4[1]), focus=seg)
            fig.text(0.06, rect[1] + rect[3] + 0.006, f"km {a:.1f} – {b:.1f}", fontsize=10, weight="bold")
        pdf.savefig(fig)
        plt.close(fig)


def cue_card_pages(pdf, route: Route, stats: dict, cues, title: str, qr_url: str | None) -> None:
    """A6 cards with large-print directions, for a handlebar or top-tube bag."""
    pages = [cues[i:i + CUES_PER_CARD] for i in range(0, len(cues), CUES_PER_CARD)] or [[]]
    for n, chunk in enumerate(pages, start=1):
        fig = plt.figure(figsize=A6)
        fig.text(0.05, 0.975, textwrap.shorten(title, 34), fontsize=10, weight="bold", va="top")
        fig.text(0.05, 0.935, f"{stats['distance_km']} km · ↑{stats['ascent_m']} m · card {n}/{len(pages)}",
                 fontsize=7.5, va="top", color="#333")
        if qr_url and n == 1:
            from cycleroutes.export.print_map import _qr_image
            ax = fig.add_axes([0.8, 0.9, 0.17, 0.09])
            ax.imshow(_qr_image(qr_url))
            ax.axis("off")
        row = 0.86 / CUES_PER_CARD
        for i, cue in enumerate(chunk):
            y = 0.89 - row * (i + 1)
            fig.patches.append(plt.Rectangle((0.04, y + 0.012), 0.025, 0.025, transform=fig.transFigure,
                                             color=config.LTS_COLORS[cue.lts], figure=fig))
            fig.text(0.08, y + 0.01, f"{cue.at_km:4.1f}", fontsize=10, weight="bold", family="monospace")
            fig.text(0.23, y + 0.01, textwrap.shorten(cue.instruction, 40), fontsize=9)
        pdf.savefig(fig)
        plt.close(fig)
