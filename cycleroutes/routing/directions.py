"""Turn-by-turn cue sheet from a Route (for screen and the printed map)."""

from dataclasses import asdict, dataclass

from cycleroutes.routing import geo
from cycleroutes.routing.route import Route
from cycleroutes.scoring import tags

TURN_THRESHOLD_DEG = 30


@dataclass
class Cue:
    at_km: float
    instruction: str
    street: str
    lts: int
    lat: float
    lon: float

    def to_dict(self) -> dict:
        return asdict(self)


def _street_name(d: dict) -> str:
    raw = d.get("name")
    name = raw[0] if isinstance(raw, list) else raw
    if isinstance(name, str) and name.strip():
        return name.strip()
    hw = tags.highway(d)
    return {"cycleway": "cycle path", "path": "path", "footway": "footpath",
            "track": "track", "service": "service road"}.get(hw, "unnamed road")


def _edge_bearings(d: dict) -> tuple[float, float]:
    """(bearing leaving the start, bearing arriving at the end) of an edge."""
    pts = list(d["geometry"].coords)
    (x0, y0), (x1, y1) = pts[0], pts[1]
    (xa, ya), (xb, yb) = pts[-2], pts[-1]
    return geo.bearing_deg(y0, x0, y1, x1), geo.bearing_deg(ya, xa, yb, xb)


def turn_word(delta: float) -> str:
    """delta: signed change in heading, degrees (-180..180, positive = right)."""
    a = abs(delta)
    side = "right" if delta > 0 else "left"
    if a < TURN_THRESHOLD_DEG:
        return "Continue"
    if a < 60:
        return f"Bear {side}"
    if a < 135:
        return f"Turn {side}"
    return f"Sharp {side}"


def cue_sheet(route: Route) -> list[Cue]:
    cues: list[Cue] = []
    data = list(route.edge_data())
    if not data:
        return cues
    first = data[0]
    lon, lat = first["geometry"].coords[0]
    start_bearing = _edge_bearings(first)[0]
    cues.append(Cue(0.0, f"Start heading {geo.compass_word(start_bearing)} on "
                    f"{_street_name(first)}", _street_name(first), first["lts"], lat, lon))

    dist = first["length"]
    prev_street, prev_arrival = _street_name(first), _edge_bearings(first)[1]
    for d in data[1:]:
        street = _street_name(d)
        leave, arrive = _edge_bearings(d)
        delta = (leave - prev_arrival + 540) % 360 - 180
        turning = abs(delta) >= TURN_THRESHOLD_DEG
        if street != prev_street or (turning and abs(delta) >= 60):
            lon, lat = d["geometry"].coords[0]
            verb = turn_word(delta)
            text = f"{verb} onto {street}" if verb != "Continue" else f"Continue onto {street}"
            cues.append(Cue(round(dist / 1000, 2), text, street, d["lts"], lat, lon))
        prev_street, prev_arrival = street, arrive
        dist += d["length"]

    lon, lat = data[-1]["geometry"].coords[-1]
    label = "Arrive back at start" if route.kind == "loop" else "Arrive at destination"
    cues.append(Cue(round(dist / 1000, 2), label, "", data[-1]["lts"], lat, lon))
    return _merge_same_street(cues)


GENERIC_STREETS = {"cycle path", "path", "footpath", "track", "service road", "unnamed road"}
JOG_MERGE_KM = 0.15


def _merge_same_street(cues: list[Cue]) -> list[Cue]:
    """Tidy the cue sheet.

    - drop 'Continue onto X' when X is the street we are already on;
    - collapse a run of turns along unnamed service roads/paths (campus
      driveways, alleys) into one 'Follow the ...' cue instead of a zig-zag
      of 'Turn left onto service road' every few metres.
    """
    out: list[Cue] = []
    for c in cues:
        prev = out[-1] if out else None
        if prev and c.street == prev.street:
            if c.instruction.startswith("Continue"):
                continue
            if c.street in GENERIC_STREETS and c.at_km - prev.at_km < JOG_MERGE_KM:
                verb = prev.instruction.split(" onto ")[0]
                if verb == "Continue":
                    prev.instruction = f"Follow the {c.street}"
                elif not verb.startswith(("Start", "Follow")) and "then follow" not in verb:
                    prev.instruction = f"{verb}, then follow the {c.street}"
                prev.lts = max(prev.lts, c.lts)
                continue
        out.append(c)
    return out
