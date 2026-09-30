"""Dependency-free NMEA 0183 parsing for GPS receivers (RMC + GGA).

Ported from gps-tracker's SerialGPSProvider and pyNav's GPSProvider (which used
pynmea2), with two improvements: checksums are verified, and multi-constellation
talkers ($GN.., $GL.., $GA..) are accepted as well as $GP...
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

KNOTS_TO_KMH = 1.852
SENTENCE_RE = re.compile(r"^\$(G[PNLAB])(RMC|GGA),")


@dataclass
class Fix:
    """One position report, whatever its source (serial GPS, phone, IP lookup)."""

    latitude: float
    longitude: float
    timestamp: float                  # unix seconds
    altitude: float | None = None     # metres
    speed_kmh: float | None = None
    heading: float | None = None      # degrees true
    accuracy_m: float | None = None
    satellites: int | None = None
    hdop: float | None = None
    fix_quality: int | None = None
    source: str = "unknown"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None and k != "extra"}


def checksum_ok(sentence: str) -> bool:
    """True if the *XX checksum matches (sentences without one are accepted)."""
    if "*" not in sentence:
        return True
    body, _, given = sentence.strip()[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(given[:2], 16)
    except ValueError:
        return False


def _coord(value: str, hemi: str) -> float | None:
    """'4807.038', 'N' -> 48.1173 (ddmm.mmmm to decimal degrees)."""
    if not value or not hemi:
        return None
    dot = value.index(".") if "." in value else len(value)
    degrees = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    dec = degrees + minutes / 60
    return -dec if hemi in ("S", "W") else dec


def _float(v: str) -> float | None:
    try:
        return float(v) if v else None
    except ValueError:
        return None


def estimate_accuracy_m(fix_quality: int | None, satellites: int | None, hdop: float | None) -> float | None:
    """Rough horizontal accuracy from fix quality, satellite count and HDOP (pyNav heuristic)."""
    if fix_quality is None:
        return None
    if fix_quality == 0:
        return 999.0
    base = {1: 5.0, 2: 2.0}.get(fix_quality, 1.0 if fix_quality >= 3 else 10.0)
    sats = satellites or 0
    sat_mult = 0.8 if sats >= 8 else 1.0 if sats >= 6 else 1.5 if sats >= 4 else 3.0
    h = hdop or 0
    hdop_mult = 1.0 if h < 2 else 1.2 if h < 5 else 1.5 if h < 10 else 2.0 if h < 20 else 3.0
    return round(base * sat_mult * hdop_mult, 1)


class NmeaParser:
    """Feed NMEA lines; returns a Fix whenever an RMC sentence gives a valid position.

    GGA sentences update altitude/satellites/HDOP, which are merged into the next fix.
    """

    def __init__(self, source: str = "Serial GPS"):
        self.source = source
        self.altitude = self.satellites = self.hdop = self.fix_quality = None
        self.last_fix: Fix | None = None

    def feed(self, line: str) -> Fix | None:
        line = line.strip()
        m = SENTENCE_RE.match(line)
        if not m or not checksum_ok(line):
            return None
        fields = line.split("*")[0].split(",")
        if m.group(2) == "GGA":
            self._gga(fields)
            return None
        return self._rmc(fields)

    def _gga(self, f: list[str]) -> None:
        # $GPGGA,time,lat,N,lon,E,quality,sats,hdop,alt,M,...
        if len(f) < 10:
            return
        self.fix_quality = int(f[6]) if f[6].isdigit() else None
        self.satellites = int(f[7]) if f[7].isdigit() else None
        self.hdop = _float(f[8])
        self.altitude = _float(f[9])

    def _rmc(self, f: list[str]) -> Fix | None:
        # $GPRMC,hhmmss.ss,A,lat,N,lon,E,knots,course,ddmmyy,...
        if len(f) < 10 or f[2] != "A":
            return None
        lat, lon = _coord(f[3], f[4]), _coord(f[5], f[6])
        if lat is None or lon is None:
            return None
        knots = _float(f[7])
        fix = Fix(
            latitude=round(lat, 7), longitude=round(lon, 7), timestamp=_timestamp(f[1], f[9]),
            altitude=self.altitude, speed_kmh=round(knots * KNOTS_TO_KMH, 2) if knots is not None else None,
            heading=_float(f[8]), satellites=self.satellites, hdop=self.hdop,
            fix_quality=self.fix_quality, source=self.source,
            accuracy_m=estimate_accuracy_m(self.fix_quality if self.fix_quality is not None else 1,
                                           self.satellites, self.hdop),
        )
        self.last_fix = fix
        return fix


def _timestamp(hhmmss: str, ddmmyy: str) -> float:
    try:
        dt = datetime.strptime(ddmmyy + hhmmss.split(".")[0], "%d%m%y%H%M%S")
        frac = float("0." + hhmmss.split(".")[1]) if "." in hhmmss else 0.0
        return dt.replace(tzinfo=timezone.utc).timestamp() + frac
    except (ValueError, IndexError):
        return datetime.now(timezone.utc).timestamp()


def to_nmea_rmc(fix: Fix) -> str:
    """Encode a fix as a $GPRMC sentence (for feeding other navigation software)."""
    dt = datetime.fromtimestamp(fix.timestamp, timezone.utc)

    def dm(value: float, width: int) -> str:
        v = abs(value)
        deg = int(v)
        return f"{deg:0{width}d}{(v - deg) * 60:07.4f}"
    knots = (fix.speed_kmh or 0) / KNOTS_TO_KMH
    body = (f"GPRMC,{dt:%H%M%S}.00,A,{dm(fix.latitude, 2)},{'N' if fix.latitude >= 0 else 'S'},"
            f"{dm(fix.longitude, 3)},{'E' if fix.longitude >= 0 else 'W'},{knots:.1f},"
            f"{fix.heading or 0:.1f},{dt:%d%m%y},,,A")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return f"${body}*{calc:02X}"
