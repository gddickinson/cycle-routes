"""Recorded rides in SQLite (replaces gps-tracker's CSV log and pyNav's sensor DB)."""

import csv
import io
import sqlite3
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

from cycleroutes import config
from cycleroutes.routing.geo import haversine_m
from cycleroutes.tracking.nmea import Fix

SCHEMA = """
CREATE TABLE IF NOT EXISTS rides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    started REAL NOT NULL,
    ended REAL,
    source TEXT,
    route_id TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS points (
    ride_id INTEGER NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
    t REAL NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
    ele REAL, speed_kmh REAL, heading REAL, accuracy_m REAL
);
CREATE INDEX IF NOT EXISTS points_ride ON points(ride_id, t);
"""
CSV_FIELDS = ["time_utc", "latitude", "longitude", "elevation_m", "speed_kmh", "heading", "accuracy_m"]


class RideStore:
    def __init__(self, path: Path = config.RIDES_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        try:            # older databases: add the travel-mode column
            self._db.execute("ALTER TABLE rides ADD COLUMN mode TEXT DEFAULT 'bike'")
        except sqlite3.OperationalError:
            pass
        self._lock = threading.Lock()

    def start(self, name: str, source: str = "phone", route_id: str | None = None, mode: str = "bike") -> int:
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO rides (name, started, source, route_id, mode) VALUES (?,?,?,?,?)",
                                   (name, time.time(), source, route_id, mode))
            return int(cur.lastrowid)

    def add_fixes(self, ride_id: int, fixes: list[Fix]) -> int:
        rows = [(ride_id, f.timestamp, f.latitude, f.longitude, f.altitude, f.speed_kmh,
                 f.heading, f.accuracy_m) for f in fixes]
        with self._lock, self._db:
            self._db.executemany("INSERT INTO points VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def finish(self, ride_id: int, summary_json: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE rides SET ended = ?, summary = ? WHERE id = ?",
                             (time.time(), summary_json, ride_id))

    def delete(self, ride_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM rides WHERE id = ?", (ride_id,)).rowcount > 0

    def ride(self, ride_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
        return dict(row) if row else None

    def rides(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT r.*, COUNT(p.t) AS n_points FROM rides r LEFT JOIN points p ON p.ride_id = r.id "
                "GROUP BY r.id ORDER BY r.started DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def points(self, ride_id: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT t, lat, lon, ele, speed_kmh, heading, accuracy_m FROM points "
                                    "WHERE ride_id = ? ORDER BY t", (ride_id,)).fetchall()
        return [dict(r) for r in rows]


SPIKE_KMH = 80.0


def drop_spikes(points: list[dict]) -> list[dict]:
    """Remove single-point GPS glitches: a fix that jumps away and straight back.

    A point is a spike when the speeds into and out of it are both implausible
    but skipping it gives a plausible speed. Consistently fast movement (a car,
    or a replayed track) is kept - only the out-and-back jump pattern is removed.
    """
    if len(points) < 3:
        return points

    def kmh(a, b):
        dt = b["t"] - a["t"]
        return float(haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])) / dt * 3.6 if dt > 0 else 0.0
    kept = [points[0]]
    for i in range(1, len(points) - 1):
        prev, cur, nxt = kept[-1], points[i], points[i + 1]
        if kmh(prev, cur) > SPIKE_KMH and kmh(cur, nxt) > SPIKE_KMH and kmh(prev, nxt) < SPIKE_KMH / 2:
            continue
        kept.append(cur)
    kept.append(points[-1])
    return kept


def track_stats(points: list[dict]) -> dict:
    """Distance, moving time and speeds straight from the GPS points."""
    n_raw = len(points)
    points = drop_spikes(points)
    if len(points) < 2:
        return {"distance_km": 0.0, "elapsed_min": 0.0, "moving_min": 0.0, "avg_moving_kmh": 0.0,
                "max_kmh": 0.0, "points": n_raw, "spikes_removed": n_raw - len(points)}
    dist = moving_s = max_kmh = 0.0
    for a, b in zip(points[:-1], points[1:]):
        d = float(haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]))
        dt = b["t"] - a["t"]
        if dt <= 0:
            continue
        kmh = d / dt * 3.6
        dist += d
        if kmh >= 2.0:      # stopped at lights etc. doesn't count as moving
            moving_s += dt
            max_kmh = max(max_kmh, kmh)
    elapsed = points[-1]["t"] - points[0]["t"]
    return {"distance_km": round(dist / 1000, 2), "elapsed_min": round(elapsed / 60, 1),
            "moving_min": round(moving_s / 60, 1),
            "avg_moving_kmh": round(dist / 1000 / (moving_s / 3600), 1) if moving_s else 0.0,
            "max_kmh": round(max_kmh, 1), "points": n_raw, "spikes_removed": n_raw - len(points)}


def ride_gpx(ride: dict, points: list[dict]) -> str:
    from datetime import datetime, timezone
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="CycleRoutes" xmlns="http://www.topografix.com/GPX/1/1">',
             f"  <trk><name>{escape(ride['name'])}</name><trkseg>"]
    for p in points:
        ts = datetime.fromtimestamp(p["t"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ele = f"<ele>{p['ele']:.1f}</ele>" if p["ele"] is not None else ""
        lines.append(f'    <trkpt lat="{p["lat"]:.7f}" lon="{p["lon"]:.7f}">{ele}<time>{ts}</time></trkpt>')
    lines += ["  </trkseg></trk>", "</gpx>"]
    return "\n".join(lines)


def ride_csv(points: list[dict]) -> str:
    """Same columns as gps-tracker's CSV log, plus accuracy."""
    from datetime import datetime, timezone
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_FIELDS)
    for p in points:
        w.writerow([datetime.fromtimestamp(p["t"], timezone.utc).isoformat(), p["lat"], p["lon"],
                    p["ele"], p["speed_kmh"], p["heading"], p["accuracy_m"]])
    return buf.getvalue()
