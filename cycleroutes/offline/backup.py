"""Export / import personal data (rides with GPS points, hazards, places, favourites,
street feedback, learned choices) as one JSON file."""

import json
import sqlite3
import time
from pathlib import Path

TABLES = ["rides", "points", "hazards", "feedback", "places", "favourites", "choices"]


def export_json(db_path: Path) -> dict:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    out = {"format": "cycleroutes-backup", "version": 1, "exported": time.time(), "tables": {}}
    for t in TABLES:
        try:
            out["tables"][t] = [dict(r) for r in db.execute(f"SELECT * FROM {t}")]
        except sqlite3.OperationalError:
            out["tables"][t] = []
    db.close()
    return out


def import_json(db_path: Path, backup: dict) -> dict:
    """Merge a backup into the database; ride ids are re-numbered to avoid clashes."""
    if backup.get("format") != "cycleroutes-backup":
        raise ValueError("Not a Cycle Routes backup file")
    tables = backup.get("tables", {})
    db = sqlite3.connect(db_path)
    counts = {}
    with db:
        id_map = {}
        for r in tables.get("rides", []):
            cur = db.execute("INSERT INTO rides (name, started, ended, source, route_id, summary) VALUES (?,?,?,?,?,?)",
                             (r["name"], r["started"], r.get("ended"), r.get("source"), r.get("route_id"), r.get("summary")))
            id_map[r["id"]] = cur.lastrowid
        counts["rides"] = len(id_map)
        pts = [(id_map[p["ride_id"]], p["t"], p["lat"], p["lon"], p.get("ele"), p.get("speed_kmh"),
                p.get("heading"), p.get("accuracy_m")) for p in tables.get("points", []) if p["ride_id"] in id_map]
        db.executemany("INSERT INTO points VALUES (?,?,?,?,?,?,?,?)", pts)
        counts["points"] = len(pts)
        for t in ("hazards", "places", "favourites"):
            rows = tables.get(t, [])
            for r in rows:
                r = {k: v for k, v in r.items() if k != "id"}
                db.execute(f"INSERT INTO {t} ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})", list(r.values()))
            counts[t] = len(rows)
        for t in ("feedback", "choices"):
            rows = tables.get(t, [])
            for r in rows:
                db.execute(f"INSERT INTO {t} ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})", list(r.values()))
            counts[t] = len(rows)
    db.close()
    return counts


def dumps(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))
