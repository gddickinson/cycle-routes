"""SQLite store for community reports and personal data (single-user prototype).

- hazards: rider reports (pothole, glass, close pass, flooding...) that expire and
  raise the cost of nearby streets for everyone's routing.
- feedback: thumbs up/down on a street segment, nudging its cost.
- places / favourites: saved locations and routes (with their planning parameters).
- shares: tokens for live-location links to an active ride.
"""

import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from cycleroutes import config

HAZARD_TYPES = {
    "pothole": ("Pothole / broken surface", 1.5, 60),
    "glass": ("Glass or debris", 1.4, 7),
    "close_pass": ("Close pass / aggressive traffic", 2.0, 90),
    "crossing": ("Dangerous crossing", 2.0, 180),
    "blocked": ("Bike lane blocked", 1.6, 14),
    "flooding": ("Flooding", 5.0, 3),
    "construction": ("Construction", 2.5, 30),
    "other": ("Other hazard", 1.3, 30),
}   # type -> (label, cost multiplier on nearby streets, days until it expires)

SCHEMA = """
CREATE TABLE IF NOT EXISTS hazards (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, note TEXT,
    lat REAL, lon REAL, created REAL, expires REAL, confirmations INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS feedback (u INTEGER, v INTEGER, score INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS places (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, lat REAL, lon REAL);
CREATE TABLE IF NOT EXISTS favourites (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, params TEXT,
    created REAL);
CREATE TABLE IF NOT EXISTS shares (token TEXT PRIMARY KEY, ride_id INTEGER, created REAL, expires REAL);
CREATE TABLE IF NOT EXISTS choices (profile TEXT, weights TEXT, created REAL);
"""


class CommunityStore:
    def __init__(self, path: Path = config.RIDES_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _write(self, sql: str, args=()) -> int:
        with self._lock, self._db:
            return self._db.execute(sql, args).lastrowid

    def _rows(self, sql: str, args=()) -> list[dict]:
        return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # --- hazards -----------------------------------------------------------------
    def report_hazard(self, kind: str, lat: float, lon: float, note: str = "") -> int:
        if kind not in HAZARD_TYPES:
            raise ValueError(f"Unknown hazard type '{kind}'")
        days = HAZARD_TYPES[kind][2]
        now = time.time()
        return self._write("INSERT INTO hazards (kind, note, lat, lon, created, expires) VALUES (?,?,?,?,?,?)",
                           (kind, note[:300], lat, lon, now, now + days * 86400))

    def confirm_hazard(self, hazard_id: int) -> None:
        """'Still there': bumps confirmations and extends the expiry."""
        row = self._rows("SELECT kind FROM hazards WHERE id = ?", (hazard_id,))
        if row:
            days = HAZARD_TYPES[row[0]["kind"]][2]
            self._write("UPDATE hazards SET confirmations = confirmations + 1, expires = ? WHERE id = ?",
                        (time.time() + days * 86400, hazard_id))

    def resolve_hazard(self, hazard_id: int) -> None:
        self._write("UPDATE hazards SET expires = ? WHERE id = ?", (time.time(), hazard_id))

    def hazards(self) -> list[dict]:
        rows = self._rows("SELECT * FROM hazards WHERE expires > ? ORDER BY created DESC", (time.time(),))
        for r in rows:
            r["label"] = HAZARD_TYPES[r["kind"]][0]
        return rows

    # --- street feedback --------------------------------------------------------------
    def rate_street(self, u: int, v: int, score: int) -> None:
        self._write("INSERT INTO feedback VALUES (?,?,?,?)", (min(u, v), max(u, v), 1 if score > 0 else -1, time.time()))

    def street_scores(self) -> dict[tuple[int, int], int]:
        return {(r["u"], r["v"]): r["s"] for r in
                self._rows("SELECT u, v, SUM(score) AS s FROM feedback GROUP BY u, v")}

    # --- places, favourites, learned preferences -----------------------------------
    def add_place(self, name: str, lat: float, lon: float) -> int:
        return self._write("INSERT INTO places (name, lat, lon) VALUES (?,?,?)", (name[:80], lat, lon))

    def places(self) -> list[dict]:
        return self._rows("SELECT * FROM places ORDER BY name")

    def delete(self, table: str, row_id: int) -> bool:
        if table not in ("places", "favourites", "hazards"):
            raise ValueError(table)
        with self._lock, self._db:
            return self._db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,)).rowcount > 0

    def add_favourite(self, title: str, params: dict) -> int:
        return self._write("INSERT INTO favourites (title, params, created) VALUES (?,?,?)",
                           (title[:120], json.dumps(params), time.time()))

    def favourites(self) -> list[dict]:
        rows = self._rows("SELECT * FROM favourites ORDER BY created DESC")
        for r in rows:
            r["params"] = json.loads(r["params"])
        return rows

    def record_choice(self, profile: str, weights: dict) -> None:
        self._write("INSERT INTO choices VALUES (?,?,?)", (profile, json.dumps(weights), time.time()))

    def learned_weights(self, last: int = 20) -> dict | None:
        """Average weights of the routes you actually chose to ride (most recent first)."""
        rows = self._rows("SELECT weights FROM choices ORDER BY created DESC LIMIT ?", (last,))
        if len(rows) < 3:
            return None
        ws = [json.loads(r["weights"]) for r in rows]
        return {k: round(sum(w.get(k, 0) for w in ws) / len(ws), 2) for k in ws[0]} | {"based_on": len(ws)}

    # --- live shares -----------------------------------------------------------------
    def create_share(self, ride_id: int, hours: float = 6) -> str:
        token = secrets.token_urlsafe(9)
        self._write("INSERT INTO shares VALUES (?,?,?,?)", (token, ride_id, time.time(), time.time() + hours * 3600))
        return token

    def share(self, token: str) -> dict | None:
        rows = self._rows("SELECT * FROM shares WHERE token = ? AND expires > ?", (token, time.time()))
        return rows[0] if rows else None
